# -*- coding: utf-8 -*-
"""
智能上下文管理器

在每次 LLM 调用前构建增强型消息序列，统一管理：
1. 图层上下文（启动时读取，项目变更时刷新）
2. 历史教训索引（关键词匹配注入）
3. 智能对话历史压缩（保留关键信息，截断冗余）
4. 自适应目标重注入（信号驱动，非固定间隔）

设计原则：
- 单一职责：只负责消息序列的构建，不执行工具或调用 LLM
- 无副作用：所有方法都是纯函数或仅修改内部状态
- 可独立测试：不依赖 QGIS 或 Qt
"""

import json
import os
from typing import Optional, List, Dict
from datetime import datetime


# ── 常量 ──────────────────────────────────────────────────

# 滑动窗口保留的最大消息条数（system 之外）
MAX_HISTORY_MESSAGES = 60
# 目标重注入：距上次引用的最大步数
GOAL_REINJECT_STEPS = 5
# 目标重注入：连续失败阈值
GOAL_REINJECT_FAILURES = 2
# 教训注入：最多注入条数
MAX_LESSON_INJECT = 5
# 图层过多时的截断阈值
MAX_LAYER_DETAILS = 20


class SmartContextManager:
    """
    智能上下文管理器。

    职责：
    1. 维护图层上下文（启动时读取，项目变更时刷新）
    2. 管理历史教训索引（关键词匹配注入）
    3. 智能压缩对话历史（保留关键信息，截断冗余）
    4. 按需注入目标提醒（自适应频率）
    """

    def __init__(self, system_prompt: str,
                 max_history: int = MAX_HISTORY_MESSAGES,
                 lessons_index_path: Optional[str] = None):
        """
        初始化上下文管理器。

        :param system_prompt: 基础系统提示词
        :param max_history: 滑动窗口保留的最大消息条数
        :param lessons_index_path: 教训索引 JSON 文件路径（可选）
        """
        self.system_prompt = system_prompt
        self.max_history = max_history
        self.lessons_index_path = lessons_index_path

        # 图层上下文摘要（None 表示未注入）
        self.layer_context: Optional[str] = None

        # 核心目标（用户原始输入）
        self.core_goal: Optional[str] = None

        # 教训索引：keyword → {error, fix, timestamp}
        self.lesson_index: Dict[str, dict] = {}
        if lessons_index_path:
            self._load_lessons(lessons_index_path)

        # 自适应重注入的状态跟踪
        self._consecutive_failures: int = 0
        self._steps_since_last_goal_ref: int = 0

    # ── 图层上下文 ──────────────────────────────────────

    def refresh_layer_context(self, layers_info: list):
        """
        读取当前项目图层，生成简洁摘要。

        :param layers_info: 图层信息列表，每项为 dict，含 name/type/geometry_type/feature_count/crs
        """
        if not layers_info:
            self.layer_context = None
            return

        if len(layers_info) > MAX_LAYER_DETAILS:
            type_counts: Dict[str, int] = {}
            for layer in layers_info:
                t = layer.get('type', '未知')
                type_counts[t] = type_counts.get(t, 0) + 1
            lines = [f'当前项目共有 {len(layers_info)} 个图层：']
            for t, c in type_counts.items():
                lines.append(f'- {t}: {c} 个')
            lines.append('（图层过多，仅显示摘要。需要详细信息请调用 list_layers）')
        else:
            lines = ['当前项目已加载的图层：']
            for layer in layers_info:
                name = layer.get('name', '未命名')
                ltype = layer.get('type', '未知')
                geom = layer.get('geometry_type', '')
                count = layer.get('feature_count', '?')
                crs = layer.get('crs', '')
                line = f'- {name}（{ltype}）'
                if geom:
                    line += f'，几何类型: {geom}'
                if count != '?':
                    line += f'，要素数: {count}'
                if crs:
                    line += f'，CRS: {crs}'
                lines.append(line)

        self.layer_context = '\n'.join(lines)

    # ── 教训索引 ──────────────────────────────────────

    def _load_lessons(self, path: str):
        """从 lessons_index.json 加载关键词索引。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.lesson_index = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            self.lesson_index = {}

    def save_lessons(self, path: Optional[str] = None):
        """保存教训索引到 JSON 文件。"""
        save_path = path or self.lessons_index_path
        if not save_path:
            return
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(self.lesson_index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_lesson(self, keyword: str, error_summary: str,
                   fix_suggestion: str, context: Optional[dict] = None):
        """
        添加一条教训到索引。

        :param keyword: 关键词（通常是工具名）
        :param error_summary: 错误摘要
        :param fix_suggestion: 修复建议
        :param context: 额外上下文（可选）
        """
        self.lesson_index[keyword] = {
            'error': error_summary,
            'fix': fix_suggestion,
            'timestamp': datetime.now().isoformat(),
            'context': context or {},
        }
        self.save_lessons()

    def get_relevant_lessons(self, user_input: str) -> str:
        """
        根据用户输入提取相关教训。

        :param user_input: 用户输入文本
        :return: 教训摘要文本（空字符串表示无相关教训）
        """
        if not self.lesson_index:
            return ''

        relevant = []
        user_lower = user_input.lower()
        for keyword, data in self.lesson_index.items():
            if keyword.lower() in user_lower:
                fix = data.get('fix', '')
                if fix:
                    relevant.append(f'- {keyword}: {fix}')

        if relevant:
            return '【历史经验参考】\n' + '\n'.join(relevant[:MAX_LESSON_INJECT])
        return ''

    def get_lesson_for_tool(self, tool_name: str, error_msg: str = '') -> str:
        """
        获取与指定工具相关的教训（用于执行失败时）。

        :param tool_name: 工具名
        :param error_msg: 错误信息（用于模糊匹配）
        :return: 教训摘要文本
        """
        relevant = []

        if tool_name in self.lesson_index:
            fix = self.lesson_index[tool_name].get('fix', '')
            if fix:
                relevant.append(f'- {tool_name}: {fix}')

        if error_msg:
            for keyword, data in self.lesson_index.items():
                if keyword != tool_name and keyword.lower() in error_msg.lower():
                    fix = data.get('fix', '')
                    if fix:
                        relevant.append(f'- {keyword}: {fix}')

        if relevant:
            return '【历史教训参考】\n' + '\n'.join(relevant[:MAX_LESSON_INJECT])
        return ''

    # ── 目标管理 ──────────────────────────────────────

    def set_core_goal(self, user_input: str):
        """记录本次任务的核心目标。"""
        self.core_goal = user_input
        self._steps_since_last_goal_ref = 0
        self._consecutive_failures = 0

    def record_step_result(self, is_failure: bool = False):
        """
        记录一步执行的结果，更新内部状态。

        :param is_failure: 该步是否失败
        """
        if is_failure:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
        self._steps_since_last_goal_ref += 1

    def should_reinject_goal(self) -> bool:
        """
        自适应判断是否需要重注入核心目标。

        信号驱动（非固定间隔）：
        1. 连续失败 ≥ GOAL_REINJECT_FAILURES 次
        2. 距上次引用目标已超过 GOAL_REINJECT_STEPS 步

        :return: 是否需要重注入
        """
        if self._consecutive_failures >= GOAL_REINJECT_FAILURES:
            return True
        if self._steps_since_last_goal_ref >= GOAL_REINJECT_STEPS:
            return True
        return False

    def get_goal_reminder(self) -> str:
        """
        生成目标提醒消息。

        调用后重置步数计数器。
        """
        self._steps_since_last_goal_ref = 0
        if not self.core_goal:
            return ''
        return (
            f'【核心目标回顾】用户的原始需求："{self.core_goal}"\n'
            f'请评估：(1) 已完成哪些步骤 (2) 是否偏离目标 '
            f'(3) 下一步应该做什么。如果目标已完成，直接回复。'
        )

    # ── 构建增强型消息序列 ────────────────────────────

    def build_messages(self, base_messages: list,
                       user_input: Optional[str] = None) -> list:
        """
        在每次 LLM 调用前，构建增强型消息序列。

        结构：[system + 图层 + 教训] + [历史窗口]

        注意：不修改 base_messages，返回新列表。

        :param base_messages: 原始消息列表（含 system 消息）
        :param user_input: 当前用户输入（用于匹配教训）
        :return: 增强型消息列表
        """
        # 1. 增强 system prompt
        enhanced_system = self.system_prompt

        if self.layer_context:
            enhanced_system += f'\n\n{self.layer_context}'

        if user_input:
            lessons = self.get_relevant_lessons(user_input)
            if lessons:
                enhanced_system += f'\n\n{lessons}'

        # 2. 提取非 system 消息
        non_system = [m for m in base_messages if m.get('role') != 'system']

        # 3. 滑动窗口截断
        if len(non_system) > self.max_history:
            trimmed = non_system[-self.max_history:]
            while trimmed and trimmed[0].get('role') in ('tool', 'assistant'):
                trimmed.pop(0)
            non_system = trimmed

        # 4. 组装：增强 system + 历史窗口
        return [{'role': 'system', 'content': enhanced_system}] + non_system

    def reset(self):
        """重置所有状态（用于新会话）。"""
        self.layer_context = None
        self.core_goal = None
        self._consecutive_failures = 0
        self._steps_since_last_goal_ref = 0
