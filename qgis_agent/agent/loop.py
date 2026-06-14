# -*- coding: utf-8 -*-
"""
Agent 循环

实现一个朴素的"工具调用循环"（tool-calling loop），不依赖 LangChain 的
AgentExecutor / ReAct。直接复用 LLMClient 已有的 OpenAI 工具调用接口
（create_chat_completion_with_tools），循环：

    LLM 决策 → tool_calls → 主线程执行工具 → 工具结果回灌 → 再次决策 → ...

直到 LLM 不再请求工具调用，或达到最大步数。

设计要点：
- 完整保存 OpenAI 消息序列（含 assistant 的 tool_calls 与 role=tool 结果），
  使多轮对话中模型能看到此前的工具调用上下文。
- 接入 SafetyGuard：危险工具执行前经 confirm_cb（UI 注入的弹窗回调）确认。
- 工具执行异常被捕获并作为工具结果回灌给 LLM，不污染为 assistant 消息。
- 工具的 JSON schema 由 provider.py 的 StructuredTool 自动生成，这里用
  convert_to_openai_tool 转为 OpenAI tools 格式。
"""

import json
import os
from typing import Optional, List, Dict, Callable

from .safety import create_safety_guard
from .context_manager import SmartContextManager
from .planner import GoalPlanner, TaskPlan


# 单次任务最多的工具调用步数（防止 LLM 陷入死循环）
MAX_ITERATIONS = 20
# 对话历史保留的最大消息条数（system 之外的滑动窗口上限）
MAX_HISTORY_MESSAGES = 60
# 同一 (工具名+参数) 允许的最大重复次数，超过则判定为死循环并终止
MAX_SAME_CALL = 3


class QGisAgentLoop:
    """
    QGIS Agent 循环。

    维护对话历史，驱动 LLM 进行工具调用，并把工具结果回灌给 LLM，
    直到任务完成。所有工具在调用线程（应为 Qt 主线程）同步执行，
    符合 PyQGIS 必须在主线程操作的约束。
    """

    def __init__(self, tools: List, llm_client,
                 system_prompt: Optional[str] = None,
                 lessons_index_path: Optional[str] = None):
        """
        初始化 Agent 循环。

        :param tools: 工具列表（LangChain StructuredTool，用于自动生成 schema）
        :param llm_client: LLMClient 实例
        :param system_prompt: 系统提示词（不传则自动生成）
        :param lessons_index_path: 教训索引 JSON 文件路径（可选）
        """
        self.tools = tools
        self.llm_client = llm_client
        self.system_prompt = system_prompt or self._default_system_prompt()

        # 安全守卫（接入执行链：危险操作判定、限流、日志）
        self.safety = create_safety_guard()

        # 取消/暂停控制标志
        self._cancelled = False   # 取消标志：True 时在下一个安全断点终止
        self._paused = False      # 暂停标志：True 时在下一个安全断点进入等待

        # 工具名 → StructuredTool 的映射，便于按名称派发
        self.tool_map = {t.name: t for t in tools}
        # 预转换为 OpenAI tools 格式（schema 由 StructuredTool 从函数签名生成）
        self.openai_tools = self._build_openai_tools(tools)

        # 智能上下文管理器（图层上下文 + 教训索引 + 历史压缩 + 目标追踪）
        self.context_manager = SmartContextManager(
            system_prompt=self.system_prompt,
            max_history=MAX_HISTORY_MESSAGES,
            lessons_index_path=lessons_index_path,
        )

        # 目标规划器（LLM 驱动的任务拆解）
        self.planner = GoalPlanner(llm_client=llm_client, tools=tools)

        # 当前任务计划（run 时生成）
        self.current_plan: Optional[TaskPlan] = None

        # 消息历史：完整 OpenAI 消息序列（含 tool_calls / tool 结果）
        self.messages: List[dict] = [
            {'role': 'system', 'content': self.system_prompt}
        ]

    def _build_openai_tools(self, tools: List) -> List[dict]:
        """
        将 LangChain StructuredTool 列表转换为 OpenAI tools 格式。

        convert_to_openai_tool 采用延迟导入：langchain 未安装时（如纯逻辑单测
        环境）不影响本模块导入与工具派发逻辑，仅是 schema 列表为空。

        :param tools: StructuredTool 列表
        :return: OpenAI tools 定义列表
        """
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
        except Exception:
            return []

        result = []
        for tool in tools:
            try:
                result.append(convert_to_openai_tool(tool))
            except Exception:
                # 单个工具转换失败不应拖垮整个 Agent，跳过并继续
                continue
        return result

    # ── 取消 / 暂停控制 ──────────────────────────────────────────────

    def request_cancel(self):
        """请求取消当前任务。在下一个安全断点生效。取消时自动解除暂停，避免死锁。"""
        self._cancelled = True
        self._paused = False

    def request_pause(self):
        """请求暂停当前任务。在下一个安全断点生效。"""
        self._paused = True

    def request_resume(self):
        """恢复被暂停的任务。"""
        self._paused = False

    def is_cancelled(self) -> bool:
        """检查是否已请求取消。"""
        return self._cancelled

    def is_paused(self) -> bool:
        """检查是否处于暂停状态。"""
        return self._paused

    def _check_interrupt(self) -> Optional[str]:
        """
        检查取消/暂停状态，在安全断点调用。

        :return: None 表示继续执行；字符串表示应终止（该字符串作为最终回复返回）
        """
        if self._cancelled:
            return '任务已被用户取消。'

        # 暂停期间：循环 processEvents 保持 UI 响应，直到恢复或取消
        while self._paused:
            if self._cancelled:
                return '任务已被用户取消。'
            try:
                from qgis.PyQt.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
            import time
            time.sleep(0.1)  # 避免忙等吃满 CPU

        # request_cancel() 会同时清除 _paused，导致 while 循环退出；
        # 此处再次检查 _cancelled，确保取消信号不被丢失。
        if self._cancelled:
            return '任务已被用户取消。'

        return None

    def run(self, user_input: str,
            confirm_cb: Optional[Callable[[str, dict], bool]] = None,
            progress_cb: Optional[Callable] = None) -> str:
        """
        同步运行 Agent 循环。

        :param user_input: 用户输入的自然语言指令
        :param confirm_cb: 危险操作确认回调，签名 (tool_name, params) -> bool。
                           返回 True 表示允许执行，False 表示拒绝。
                           不传则危险操作默认拒绝（安全优先）。
        :param progress_cb: 进度回调，签名 (description, current, total)。
                            每步执行时调用，供 UI 展示进度。
        :return: Agent 的最终文本回复
        """
        # ── 初始化阶段 ─────────────────────────────────────
        # 设置核心目标（用于自适应重注入）
        self.context_manager.set_core_goal(user_input)

        # 生成任务计划（LLM 拆解，失败时降级为单步）
        self.current_plan = self.planner.create_plan(user_input)

        # 追加用户消息
        self.messages.append({'role': 'user', 'content': user_input})

        # 重置取消标志（每次 run 是独立任务）。
        # 不重置 _paused：暂停是用户主动控制的状态，可能在 run 之前就设置了。
        self._cancelled = False

        # 本次任务内各 (工具名+参数) 的调用计数，用于检测重复死循环
        call_counts: Dict[str, int] = {}

        # 进度回调：展示计划
        if progress_cb and self.current_plan:
            progress_cb(self.current_plan.to_display_text(), 0,
                        len(self.current_plan.steps))

        # ── 工具调用循环 ─────────────────────────────────────
        for step_idx in range(MAX_ITERATIONS):
            # ★ 检查点 1：迭代开始（LLM 调用前）
            interrupt = self._check_interrupt()
            if interrupt:
                self.messages.append({'role': 'assistant', 'content': interrupt})
                return interrupt

            # 构建增强型消息（含图层上下文、教训、历史压缩）
            enhanced_messages = self.context_manager.build_messages(
                self.messages, user_input
            )

            # 进度回调：当前步骤
            if progress_cb and self.current_plan:
                current = self.current_plan.current_step()
                if current:
                    current.status = 'running'
                    done_count = sum(
                        1 for s in self.current_plan.steps if s.status == 'done'
                    )
                    progress_cb(
                        f'步骤 {current.step_id}: {current.description}',
                        done_count,
                        len(self.current_plan.steps),
                    )

            # 请求 LLM（带工具定义）。异常直接抛出，由上层 UI 显示
            content, tool_calls = self.llm_client.create_chat_completion_with_tools(
                messages=enhanced_messages,
                tools=self.openai_tools,
            )

            # 没有工具调用 → 任务完成，返回文本
            if not tool_calls:
                final = content or ''
                self.messages.append({'role': 'assistant', 'content': final})
                if self.current_plan:
                    self.current_plan.status = 'completed'
                    for s in self.current_plan.steps:
                        if s.status == 'pending':
                            s.status = 'skipped'
                return final

            # 有工具调用 → 先把 assistant 消息（含 tool_calls）写入历史
            assistant_msg = self._make_assistant_tool_message(content, tool_calls)
            self.messages.append(assistant_msg)

            # ★ 检查点 2：工具执行前（LLM 已返回，工具尚未执行）
            interrupt = self._check_interrupt()
            if interrupt:
                self.messages.append({'role': 'assistant', 'content': interrupt})
                return interrupt

            # 逐个执行工具调用，把结果作为 role=tool 消息回灌
            for tc, call_id in zip(tool_calls, self._call_ids(assistant_msg)):
                # 重复调用检测：同一 (工具名+参数) 重复过多次，判定为死循环。
                sig = self._call_signature(tc)
                call_counts[sig] = call_counts.get(sig, 0) + 1
                if call_counts[sig] > MAX_SAME_CALL:
                    result_text = (
                        f'错误: 工具 "{tc.name}" 以相同参数已重复调用 '
                        f'{MAX_SAME_CALL} 次仍未成功，已停止重试。'
                        f'请换一种方法，或如实向用户说明无法完成的原因。'
                    )
                    # ★ 教训记录：记录重复调用的教训
                    self._record_lesson(tc, result_text, step_idx)
                    # ★ 目标重注入：重复调用时立即注入核心目标
                    reminder = self.context_manager.get_goal_reminder()
                    if reminder:
                        self.messages.append({
                            'role': 'user', 'content': reminder,
                        })
                else:
                    result_text = self._execute_tool_call(tc, confirm_cb)

                # 更新计划状态
                is_failure = any(
                    kw in result_text
                    for kw in ('错误', '失败', '出错', '取消')
                )
                if self.current_plan:
                    current = self.current_plan.current_step()
                    if current:
                        if is_failure:
                            current.status = 'failed'
                            current.error = result_text[:100]
                        else:
                            current.status = 'done'
                            current.result_summary = result_text[:100]

                self.messages.append({
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'content': result_text,
                })

                # ★ 自适应目标重注入（信号驱动，非固定间隔）
                self.context_manager.record_step_result(is_failure=is_failure)
                if self.context_manager.should_reinject_goal():
                    reminder = self.context_manager.get_goal_reminder()
                    if reminder:
                        self.messages.append({
                            'role': 'user', 'content': reminder,
                        })

                # ★ 检查点 3：每个工具执行后
                interrupt = self._check_interrupt()
                if interrupt:
                    self.messages.append({'role': 'assistant', 'content': interrupt})
                    return interrupt

        # 超过最大步数仍未结束
        msg = f'已达到最大工具调用步数（{MAX_ITERATIONS}），任务可能未完成。'
        self.messages.append({'role': 'assistant', 'content': msg})
        return msg

    def _make_assistant_tool_message(self, content: Optional[str],
                                     tool_calls: List) -> dict:
        """
        构建带 tool_calls 的 assistant 消息（OpenAI 格式）。

        为缺失 id 的工具调用补一个稳定 id，确保后续 role=tool 消息能正确配对。

        :param content: LLM 返回的文本内容（可能为 None）
        :param tool_calls: ToolCallInfo 列表
        :return: assistant 消息字典
        """
        calls = []
        for i, tc in enumerate(tool_calls):
            call_id = getattr(tc, 'id', '') or f'call_{i}'
            calls.append({
                'id': call_id,
                'type': 'function',
                'function': {
                    'name': tc.name,
                    'arguments': json.dumps(tc.args, ensure_ascii=False),
                },
            })
        return {
            'role': 'assistant',
            'content': content or '',
            'tool_calls': calls,
        }

    @staticmethod
    def _call_ids(assistant_msg: dict) -> List[str]:
        """从 assistant 消息中提取各 tool_call 的 id（与执行顺序一致）。"""
        return [c['id'] for c in assistant_msg.get('tool_calls', [])]

    @staticmethod
    def _call_signature(tc) -> str:
        """
        生成工具调用的去重签名（工具名 + 规范化参数）。

        用于检测「同一调用反复重试」的死循环。参数按键排序后序列化，
        保证语义相同的参数得到相同签名。
        """
        try:
            args_part = json.dumps(tc.args, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            args_part = str(getattr(tc, 'args', ''))
        return f'{tc.name}::{args_part}'

    def _execute_tool_call(self, tc,
                           confirm_cb: Optional[Callable[[str, dict], bool]]) -> str:
        """
        执行单个工具调用，返回给 LLM 的结果文本。

        流程：限流检查 → 危险操作确认 → 派发执行 → 记录日志。
        任何异常都被捕获并转为错误文本回灌（不抛出、不污染 assistant）。

        :param tc: ToolCallInfo（含 name / args / id）
        :param confirm_cb: 危险操作确认回调
        :return: 工具结果文本
        """
        name = tc.name
        args = tc.args if isinstance(tc.args, dict) else {}

        # 限流
        if not self.safety.check_rate_limit():
            return '错误: 工具调用过于频繁，已触发速率限制，请稍后再试。'

        # 工具不存在
        tool = self.tool_map.get(name)
        if tool is None:
            return f'错误: 未知工具 "{name}"。'

        # 危险操作确认
        if self.safety.is_dangerous(name):
            allowed = confirm_cb(name, args) if confirm_cb else False
            if not allowed:
                return f'操作已取消: 用户拒绝执行危险工具 "{name}"。'

        # 派发执行（异常转为错误文本回灌）
        import time
        start = time.time()
        try:
            result = tool.func(**args)
            result_text = self._stringify_result(result)
        except Exception as e:
            result_text = f'工具执行出错: {e}'
        duration_ms = int((time.time() - start) * 1000)

        # 记录日志（结果做长度截断，避免日志膨胀）
        self.safety.log_call(
            tool_name=name,
            params=args,
            result=result_text[:500],
            duration_ms=duration_ms,
        )
        return result_text

    @staticmethod
    def _stringify_result(result) -> str:
        """将工具返回值统一转为字符串，供 role=tool 消息使用。"""
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return str(result)

    def _trim_history(self):
        """
        滑动窗口截断对话历史，防止超出上下文窗口。

        始终保留 system 消息；其余消息保留最近 MAX_HISTORY_MESSAGES 条。
        截断后若首条是 role=tool（孤立的工具结果，缺少对应 assistant），
        则继续向后丢弃，直到遇到 user 消息，避免消息配对损坏。

        注意：当 SmartContextManager 可用时，由 context_manager.build_messages
        替代此方法的截断逻辑。此方法保留用于向后兼容。
        """
        if len(self.messages) <= MAX_HISTORY_MESSAGES + 1:
            return

        system = self.messages[0]
        tail = self.messages[-MAX_HISTORY_MESSAGES:]

        # 丢弃开头的孤立 tool / assistant(tool_calls) 消息，直到 user 边界
        while tail and tail[0].get('role') in ('tool', 'assistant'):
            tail.pop(0)

        self.messages = [system] + tail

    def _record_lesson(self, tc, error_text: str, step: int):
        """
        记录重复调用的教训到上下文管理器的教训索引。

        :param tc: ToolCallInfo（含 name / args）
        :param error_text: 错误文本
        :param step: 当前步骤索引
        """
        self.context_manager.add_lesson(
            keyword=tc.name,
            error_summary=f'步骤 {step}: {error_text[:200]}',
            fix_suggestion='需要换思路或检查参数是否正确',
            context={'tool': tc.name, 'args': tc.args, 'step': step},
        )

    def clear_history(self):
        """清空对话历史（保留系统提示）。"""
        self.messages = [
            {'role': 'system', 'content': self.system_prompt}
        ]
        self.context_manager.reset()
        self.current_plan = None

    def add_message(self, role: str, content: str):
        """
        手动添加消息到对话历史。

        :param role: 角色 ('user' / 'assistant')
        :param content: 消息内容
        """
        self.messages.append({'role': role, 'content': content})

    def _default_system_prompt(self) -> str:
        """
        生成默认系统提示词。

        工具清单由当前注册的 self.tools 动态生成（名称 + 描述），
        避免与 provider.py 实际注册集发生漂移。
        """
        lines = [
            '你是一名专业的 QGIS 地理信息系统助手。你可以通过调用工具来操作 QGIS，'
            '帮助用户完成图层管理、空间分析、要素编辑、表达式计算、网络服务、'
            '坐标系操作等各种 GIS 任务。',
            '',
            '可用工具：',
        ]
        # 动态列出已注册工具，保证与实际能力一致
        for tool in self.tools:
            desc = (getattr(tool, 'description', '') or '').strip()
            lines.append(f'- {tool.name}: {desc}')
        lines += [
            '',
            '工作原则：',
            '1. 分析用户需求，选择合适的工具组合按顺序完成任务。',
            '2. 执行 Processing 算法前，先用 get_algorithm_info 查询必需参数。',
            '3. 编辑图层前先 start_editing，完成后用 stop_editing 提交。',
            '4. 工具调用出错时，根据错误信息调整参数后重试；'
            '但不要对同一目标反复重试完全相同的调用，换思路或如实说明失败原因。',
            '5. 用最少的工具调用完成任务，最终结果用中文清晰呈现。',
            '',
            '重要：优先使用上面列出的专用工具，不要用 execute_python_code 代替。',
            'execute_python_code 是最后手段，每次调用都会弹窗打断用户、需手动确认，'
            '只有在没有任何合适专用工具时才使用。',
            '常见任务的正确工具：',
            '- 计算面积/长度：用 evaluate_expression(layer_id, "$area" 或 "$length") 读取，'
            '或用 calculate_field 把结果写入新字段（field_type 用 "double"）。',
            '- 字段统计（求和/均值/最值）：用 field_statistics。',
            '- 空间分析（缓冲区/裁剪/相交等）：用 run_algorithm 调 Processing 算法。',
        ]
        return '\n'.join(lines)
