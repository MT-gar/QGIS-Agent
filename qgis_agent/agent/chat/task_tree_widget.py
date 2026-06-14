# -*- coding: utf-8 -*-
"""
任务进度树形控件

嵌入 chat_panel，在 Agent 执行期间实时显示任务计划的步骤状态。
每个步骤显示为一行：图标 + 描述 + 状态文本。

使用方式：
- 创建后嵌入 chat_panel 布局
- 通过 update_plan(TaskPlan) 刷新显示
- 任务完成后可折叠/隐藏
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QSizePolicy,
)
from qgis.PyQt.QtCore import Qt


class TaskTreeWidget(QWidget):
    """
    任务进度树形控件。

    显示 TaskPlan 的步骤列表，每步一行：
      ⬜ 步骤描述（待执行）
      🔄 步骤描述（执行中）
      ✅ 步骤描述（完成）
      ❌ 步骤描述（失败）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # 标题行
        self.title_label = QLabel('📋 任务计划')
        self.title_label.setStyleSheet(
            'font-weight: bold; color: #aaa; font-size: 11px;'
        )
        layout.addWidget(self.title_label)

        # 树形控件
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setStyleSheet(
            'QTreeWidget { background-color: #252525; color: #d4d4d4; '
            'font-size: 11px; border: none; }'
            'QTreeWidget::item { padding: 2px 0; }'
        )
        self.tree.setMaximumHeight(200)
        layout.addWidget(self.tree)

        # 初始隐藏（无计划时不可见）
        self.setVisible(False)

    def update_plan(self, plan):
        """
        根据 TaskPlan 更新树形显示。

        :param plan: TaskPlan 实例
        """
        if not plan or not plan.steps:
            self.setVisible(False)
            return

        self.setVisible(True)

        # 更新标题
        self.title_label.setText(f'📋 任务计划（{plan.progress_text()}）')

        # 重建树
        self.tree.clear()
        for step in plan.steps:
            display = f'{step.icon()} {step.description}'
            if step.error:
                display += f'  ⚠️ {step.error[:50]}'

            item = QTreeWidgetItem([display])
            if step.status == 'running':
                item.setForeground(0, Qt.GlobalColor.yellow)
            elif step.status == 'failed':
                item.setForeground(0, Qt.GlobalColor.red)
            elif step.status == 'done':
                item.setForeground(0, Qt.GlobalColor.green)

            self.tree.addTopLevelItem(item)

        # 自动滚动到当前步骤
        current = plan.current_step()
        if current:
            idx = plan.steps.index(current)
            if idx < self.tree.topLevelItemCount():
                self.tree.scrollToItem(
                    self.tree.topLevelItem(idx),
                    self.tree.ScrollHint.PositionAtCenter,
                )

    def clear(self):
        """清空并隐藏。"""
        self.tree.clear()
        self.setVisible(False)
