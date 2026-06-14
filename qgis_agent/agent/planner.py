# -*- coding: utf-8 -*-
"""
目标规划器

将用户意图拆解为结构化步骤清单（TaskPlan），供执行引擎逐步执行。
支持：
- LLM 驱动的自动拆解
- 降级处理（拆解失败时回退到单步执行）
- 步骤状态追踪（pending/running/done/failed/skipped）
- 进度文本生成（供 UI 展示）
"""

import json
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class PlanStep:
    """计划中的一个步骤。"""
    step_id: str           # 如 'step_1'
    description: str       # 自然语言描述
    tool_hint: str = ''    # 建议使用的工具名（可选）
    status: str = 'pending'  # pending / running / done / failed / skipped
    result_summary: str = '' # 执行结果摘要
    error: str = ''          # 失败时的错误信息

    STATUS_ICONS = {
        'pending': '⬜',
        'running': '🔄',
        'done': '✅',
        'failed': '❌',
        'skipped': '⏭️',
    }

    def icon(self) -> str:
        return self.STATUS_ICONS.get(self.status, '❓')


@dataclass
class TaskPlan:
    """任务计划。"""
    goal: str                    # 用户原始目标
    steps: List[PlanStep] = field(default_factory=list)
    created_at: str = ''
    status: str = 'planning'     # planning / executing / completed / failed

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    def current_step(self) -> Optional[PlanStep]:
        """返回当前正在执行或待执行的第一个步骤。"""
        for s in self.steps:
            if s.status in ('pending', 'running'):
                return s
        return None

    def progress_text(self) -> str:
        """返回 'done/total' 格式的进度文本。"""
        done = sum(1 for s in self.steps if s.status == 'done')
        total = len(self.steps)
        return f'{done}/{total}'

    def to_display_text(self) -> str:
        """生成供 UI 展示的进度文本。"""
        lines = [f'📋 任务计划（{self.progress_text()}）:']
        for s in self.steps:
            lines.append(f'  {s.icon()} {s.description}')
            if s.error:
                lines.append(f'     ⚠️ {s.error}')
        return '\n'.join(lines)

    def mark_step(self, step_id: str, status: str,
                  result_summary: str = '', error: str = ''):
        """更新指定步骤的状态。"""
        for s in self.steps:
            if s.step_id == step_id:
                s.status = status
                if result_summary:
                    s.result_summary = result_summary
                if error:
                    s.error = error
                break

    def advance_to_next(self) -> Optional[PlanStep]:
        """
        将当前 running 步骤标记为 done，返回下一个 pending 步骤。
        如果没有更多步骤，返回 None。
        """
        # 标记当前 running 为 done
        for s in self.steps:
            if s.status == 'running':
                s.status = 'done'
                break
        # 返回下一个 pending
        return self.current_step()

    def skip_current(self, reason: str = '') -> Optional[PlanStep]:
        """
        跳过当前 pending/running 步骤，返回下一个。
        """
        for s in self.steps:
            if s.status in ('pending', 'running'):
                s.status = 'skipped'
                if reason:
                    s.result_summary = f'跳过: {reason}'
                break
        return self.current_step()

    def has_pending(self) -> bool:
        """是否有待执行的步骤。"""
        return any(s.status in ('pending', 'running') for s in self.steps)

    def is_complete(self) -> bool:
        """所有步骤是否都已完成（done 或 skipped）。"""
        return all(s.status in ('done', 'skipped') for s in self.steps)

    def has_failure(self) -> bool:
        """是否有失败的步骤。"""
        return any(s.status == 'failed' for s in self.steps)


class GoalPlanner:
    """
    目标规划器：用 LLM 将用户意图拆解为结构化步骤。

    拆解失败时降级为单步执行计划（不阻塞任务）。
    """

    PLAN_SYSTEM_PROMPT = (
        '你是一个 GIS 任务规划助手。请将用户需求拆解为具体的执行步骤。\n'
        '以 JSON 数组格式返回，每个元素包含：\n'
        '- step_id: 步骤标识（如 "step_1"）\n'
        '- description: 步骤的自然语言描述\n'
        '- tool_hint: 建议使用的工具名（从可用工具中选择，可为空字符串）\n\n'
        '只返回 JSON 数组，不要其他文字。确保 JSON 格式正确。'
    )

    def __init__(self, llm_client, tools: list):
        """
        :param llm_client: LLMClient 实例
        :param tools: 工具列表（StructuredTool）
        """
        self.llm_client = llm_client
        self.tools = tools

    def _build_tools_summary(self) -> str:
        """构建工具摘要供规划 prompt 使用。"""
        lines = []
        for t in self.tools:
            desc = (getattr(t, 'description', '') or '').strip()
            if len(desc) > 80:
                desc = desc[:80] + '...'
            lines.append(f'- {t.name}: {desc}')
        return '\n'.join(lines)

    def create_plan(self, user_input: str) -> TaskPlan:
        """
        用 LLM 生成任务计划。

        拆解失败时返回单步降级计划。

        :param user_input: 用户输入
        :return: TaskPlan 实例
        """
        tools_summary = self._build_tools_summary()
        user_prompt = (
            f'用户需求：{user_input}\n\n'
            f'可用工具：\n{tools_summary}'
        )

        try:
            response = self.llm_client.create_chat_completion([
                {'role': 'system', 'content': self.PLAN_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_prompt},
            ])

            # 解析 JSON（兼容 LLM 可能返回 markdown 代码块的情况）
            response = response.strip()
            if response.startswith('```'):
                lines = response.split('\n')
                response = '\n'.join(
                    l for l in lines
                    if not l.strip().startswith('```')
                ).strip()

            steps_data = json.loads(response)
            if not isinstance(steps_data, list):
                raise ValueError('期望 JSON 数组')

            steps = []
            for i, s in enumerate(steps_data):
                if not isinstance(s, dict):
                    continue
                steps.append(PlanStep(
                    step_id=s.get('step_id', f'step_{i+1}'),
                    description=s.get('description', f'步骤 {i+1}'),
                    tool_hint=s.get('tool_hint', ''),
                ))

            if not steps:
                raise ValueError('解析出空步骤列表')

            return TaskPlan(
                goal=user_input,
                steps=steps,
                status='executing',
            )

        except Exception:
            # 降级：单步执行计划
            return TaskPlan(
                goal=user_input,
                steps=[PlanStep(
                    step_id='step_1',
                    description=user_input,
                    tool_hint='',
                )],
                status='executing',
            )
