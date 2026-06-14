# -*- coding: utf-8 -*-
"""
QGIS Agent 聊天面板

实现嵌入 QGIS 的聊天 UI 面板。
继承 QgsDockWidget，以停靠窗口形式嵌入 QGIS 界面。

面板包含：
- 顶部：会话管理栏（新建会话、切换会话）+ LLM 配置（后端、模型、API Key）
- 中间：聊天消息列表（用户消息 vs Agent 回复）
- 底部：输入框、发送按钮、暂停/恢复按钮、停止按钮

线程模型：采用"同步执行 + 保持响应"。Agent 循环在 Qt 主线程同步运行
（PyQGIS 工具必须在主线程执行），执行期间禁用输入并通过 processEvents
让界面重绘，LLM 请求自带超时防止永久卡死。
"""

import html
from typing import Optional

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QComboBox, QLabel,
    QGroupBox, QMessageBox, QApplication,
)
from qgis.PyQt.QtGui import QTextCursor
from qgis.PyQt.QtCore import pyqtSignal, QTimer

# 版本兼容性
try:
    from ..compat import safe_process_events
except ImportError:
    safe_process_events = lambda: None
from qgis.gui import QgsDockWidget


class ChatPanel(QgsDockWidget):
    """
    QGIS Agent 聊天面板。

    作为 QGIS 的停靠窗口，提供完整的聊天界面和配置功能。
    """

    # 信号：用户发送消息（供外部监听，可选）
    message_sent = pyqtSignal(str)

    def __init__(self, iface, title: str = 'QGIS Agent'):
        """
        初始化聊天面板。

        :param iface: QGIS 接口对象
        :param title: 面板标题
        """
        super().__init__(None)
        self.iface = iface
        self.setWindowTitle(title)
        self.setObjectName('QgisAgentPanel')

        # 设置面板大小
        self.resize(400, 600)

        # Agent 延迟初始化（首次发送消息时创建）
        self.agent = None
        # 会话管理器提前创建，使新建/切换/清空会话在首次发消息前即可用
        self.session_manager = self._create_session_manager()

        # 构建 UI
        self._setup_ui()
        # 初始化会话下拉框
        self._refresh_session_combo()

    @staticmethod
    def _create_session_manager():
        """延迟导入并创建 SessionManager（避免循环依赖与启动开销）。"""
        try:
            from ..session import SessionManager
            return SessionManager()
        except Exception:
            return None

    def _setup_ui(self):
        """构建面板 UI（垂直布局：工具栏 / 聊天区 / 任务树 / 输入区）。"""
        central_widget = QWidget()
        self.setWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # === 1. 工具栏 ===
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)

        # === 2. 聊天消息区域 ===
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setAcceptRichText(False)
        self.chat_display.setStyleSheet(
            'QTextEdit { background-color: #1e1e1e; color: #d4d4d4; '
            'font-family: Consolas, Courier; font-size: 12px; }'
        )
        main_layout.addWidget(self.chat_display)

        # === 3. 任务进度树（初始隐藏，有计划时显示）===
        from .task_tree_widget import TaskTreeWidget
        self.task_tree = TaskTreeWidget()
        main_layout.addWidget(self.task_tree)

        # === 4. 输入区域 ===
        input_area = self._create_input_area()
        main_layout.addWidget(input_area)

    def _create_toolbar(self) -> QGroupBox:
        """创建设置和会话管理工具栏。"""
        group = QGroupBox('设置')
        layout = QHBoxLayout()

        # 会话选择下拉框
        layout.addWidget(QLabel('会话:'))
        self.session_combo = QComboBox()
        self.session_combo.currentIndexChanged.connect(self._on_session_changed)
        layout.addWidget(self.session_combo)

        # 新建会话按钮
        btn_new = QPushButton('+ 新建')
        btn_new.clicked.connect(self._create_new_session)
        layout.addWidget(btn_new)

        # 清空会话按钮
        btn_clear = QPushButton('清空')
        btn_clear.clicked.connect(self._clear_session)
        layout.addWidget(btn_clear)

        layout.addStretch()

        # LLM 提供商选择
        layout.addWidget(QLabel('LLM:'))
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(['openai', 'anthropic', 'ollama'])
        layout.addWidget(self.provider_combo)

        # 模型输入
        layout.addWidget(QLabel('模型:'))
        self.model_input = QLineEdit('gpt-4o')
        self.model_input.setPlaceholderText('模型名称')
        layout.addWidget(self.model_input)

        # 端点输入（自定义 OpenAI 兼容服务的 base_url，如 agnes-ai；留空则用官方默认）
        layout.addWidget(QLabel('端点:'))
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText('base_url（可选，自定义端点填这里）')
        layout.addWidget(self.base_url_input)

        # API Key 输入（仅存于内存，不写入会话/磁盘）
        layout.addWidget(QLabel('API Key:'))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText('API Key')
        layout.addWidget(self.api_key_input)

        # 配置项变更后，使已建好的 Agent 失效，下次发送时按新配置重建。
        # 用 editingFinished（失焦/回车触发）避免每次按键都重置。
        self.provider_combo.currentIndexChanged.connect(self._invalidate_agent)
        self.model_input.editingFinished.connect(self._invalidate_agent)
        self.base_url_input.editingFinished.connect(self._invalidate_agent)
        self.api_key_input.editingFinished.connect(self._invalidate_agent)

        group.setLayout(layout)
        return group

    def _create_input_area(self) -> QWidget:
        """创建输入区域（输入框 + 发送按钮）。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 输入框
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText('输入指令，例如：列出当前项目所有图层...')
        self.message_input.returnPressed.connect(self._send_message)
        layout.addWidget(self.message_input)

        # 发送按钮
        self.send_button = QPushButton('发送')
        self.send_button.clicked.connect(self._send_message)
        layout.addWidget(self.send_button)

        # 暂停按钮（仅在 Agent 运行时可见）
        self.pause_button = QPushButton('暂停')
        self.pause_button.clicked.connect(self._toggle_pause)
        self.pause_button.setVisible(False)
        layout.addWidget(self.pause_button)

        # 停止按钮（仅在 Agent 运行时可见）
        self.stop_button = QPushButton('停止')
        self.stop_button.clicked.connect(self._cancel_agent)
        self.stop_button.setVisible(False)
        layout.addWidget(self.stop_button)

        return widget

    def _send_message(self):
        """发送用户消息并获取 Agent 回复。"""
        text = self.message_input.text().strip()
        if not text:
            return

        # 清空输入框、显示用户消息
        self.message_input.clear()
        self._append_message('user', text)

        # 发送信号（供外部可选监听）
        self.message_sent.emit(text)

        # 同步执行 Agent（执行期间禁用输入，保持界面响应）
        self._run_agent(text)

    def _run_agent(self, user_input: str):
        """
        运行 Agent 获取回复。

        执行期间禁用输入控件并显示"思考中"，结束后在 finally 中恢复，
        确保即使出错也不会让界面卡在禁用状态。

        :param user_input: 用户输入
        """
        # 确保 Agent 已初始化
        if self.agent is None:
            self._init_agent()
        if self.agent is None:
            self._append_message('error', 'Agent 初始化失败。请检查 LLM 配置。')
            return

        # 首次运行时注入图层上下文
        if not hasattr(self, '_layer_context_injected'):
            self._inject_layer_context()
            self._layer_context_injected = True

        # 禁用输入，提示思考中
        self._set_busy(True)
        # 确保新任务不被前一次的暂停状态阻塞
        if self.agent.is_paused():
            self.agent.request_resume()
        self._append_message('system', '思考中…')
        safe_process_events()

        try:
            # 进度回调：更新任务树和进度标签
            def on_progress(description, current, total):
                # 更新任务树
                if hasattr(self, 'task_tree') and self.agent.current_plan:
                    self.task_tree.update_plan(self.agent.current_plan)

            # 运行 Agent（注入危险操作确认回调 + 进度回调）
            response = self.agent.run(
                user_input,
                confirm_cb=self._confirm_dangerous,
                progress_cb=on_progress,
            )
            self._append_message('agent', response)

            # 任务完成后更新任务树最终状态
            if hasattr(self, 'task_tree') and self.agent.current_plan:
                self.task_tree.update_plan(self.agent.current_plan)

            # 保存到会话
            if self.session_manager:
                self.session_manager.add_message('user', user_input)
                self.session_manager.add_message('assistant', response)
                self._refresh_session_combo()

        except Exception as e:
            self._append_message('error', f'Agent 执行出错: {e}')
        finally:
            self._set_busy(False)
            # 任务树：仅在计划真正完成时延迟清理，出错或取消时保留供用户查看
            if hasattr(self, 'task_tree') and self.agent:
                plan = self.agent.current_plan
                if plan and plan.is_complete():
                    # 完成后延迟 5 秒清理，让用户看到最终状态
                    QTimer.singleShot(5000, self.task_tree.clear)
                elif plan and plan.has_failure():
                    # 有失败步骤，保留任务树不清理
                    pass

    def _set_busy(self, busy: bool):
        """切换忙碌状态：禁用/启用输入控件，显示/隐藏暂停和停止按钮。"""
        self.send_button.setEnabled(not busy)
        self.message_input.setEnabled(not busy)
        self.pause_button.setVisible(busy)
        self.stop_button.setVisible(busy)
        self.pause_button.setText('暂停')  # 重置按钮文本
        safe_process_events()

    def _toggle_pause(self):
        """切换暂停/恢复状态。"""
        if not self.agent:
            return
        if self.agent.is_paused():
            self.agent.request_resume()
            self.pause_button.setText('暂停')
            self._append_message('system', '任务已恢复。')
        else:
            self.agent.request_pause()
            self.pause_button.setText('恢复')
            self._append_message('system', '任务已暂停。点击"恢复"继续。')

    def _cancel_agent(self):
        """取消当前 Agent 任务。"""
        if not self.agent:
            return
        self.agent.request_cancel()
        self._append_message('system', '正在取消任务…')

    def _confirm_dangerous(self, tool_name: str, params: dict) -> bool:
        """
        危险操作确认回调（在主线程弹窗）。

        由 Agent 循环在执行危险工具前调用。

        :param tool_name: 工具名称
        :param params: 工具参数
        :return: 用户是否允许执行
        """
        summary = ', '.join(f'{k}={v}' for k, v in (params or {}).items())
        if len(summary) > 300:
            summary = summary[:300] + '…'
        reply = QMessageBox.question(
            self,
            '危险操作确认',
            f'Agent 请求执行可能有风险的操作：\n\n'
            f'工具: {tool_name}\n参数: {summary}\n\n是否允许？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _invalidate_agent(self):
        """
        使当前 Agent 失效，下次发送消息时按最新配置重建。

        当用户修改 LLM 提供商 / 模型 / 端点 / API Key 后调用，确保新配置生效
        （否则 Agent 仅在首次发送时构建，后续改配置不起作用）。
        """
        self.agent = None

    def _init_agent(self):
        """
        初始化 Agent。

        读取配置面板的设置，创建工具列表、LLM 客户端与 Agent 循环。
        """
        try:
            # 获取桥接器
            from ..tools.qgis_bridge import get_bridge
            bridge = get_bridge(iface=self.iface)

            # 创建工具列表
            from ..provider import create_qgis_tools
            tools = create_qgis_tools(bridge, self.iface)

            # 创建 LLM 客户端
            provider = self.provider_combo.currentText()
            model = self.model_input.text() or 'gpt-4o'
            # 修复 Windows 路径分隔符问题：litellm 要求正斜杠
            model = model.replace('\\', '/')
            api_key = self.api_key_input.text()
            base_url = self.base_url_input.text().strip() or None

            from ..client import create_client
            client = create_client({
                'provider': provider,
                'model': model,
                'api_key': api_key,
                'base_url': base_url,
            })

            # 教训索引路径（插件目录下的 lessons_index.json）
            import os
            lessons_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'lessons_index.json',
            )

            # 创建 Agent 循环（含上下文管理器和规划器）
            from ..loop import QGisAgentLoop
            self.agent = QGisAgentLoop(
                tools=tools,
                llm_client=client,
                lessons_index_path=lessons_path,
            )

            self._append_message('system', '✅ Agent 已就绪。请输入您的 GIS 任务。')

        except Exception:
            import traceback
            self._append_message('error', f'Agent 初始化失败:\n{traceback.format_exc()}')

    def _inject_layer_context(self):
        """读取当前项目图层信息，注入 Agent 上下文。"""
        if not self.agent:
            return
        try:
            from ..tools.iface_tools import list_layers
            layers_info = list_layers()
            if layers_info:
                self.agent.context_manager.refresh_layer_context(layers_info)
        except Exception:
            pass  # 图层读取失败不影响正常功能

    def _append_message(self, role: str, text: str):
        """
        在聊天显示区域追加消息（纯文本方式，避免 HTML 注入）。

        :param role: 角色 ('user' / 'agent' / 'assistant' / 'error' / 'system')
        :param text: 消息文本
        """
        # 角色标题映射（assistant 与 agent 等同，兼容历史会话存储的 assistant）
        headers = {
            'user': '\n--- 用户 ---\n',
            'agent': '\n--- Agent ---\n',
            'assistant': '\n--- Agent ---\n',
            'error': '\n--- ❌ 错误 ---\n',
            'system': '\n--- 💬 ---\n',
        }
        header = headers.get(role, f'\n--- {role} ---\n')

        # 以纯文本插入，杜绝 LLM 输出被当作富文本渲染
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(f'{header}{text}\n')

        # 自动滚动到底部
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_session_changed(self, index: int):
        """会话切换回调（通过下拉项绑定的 session_id 定位会话）。"""
        if index < 0:
            return
        session_id = self.session_combo.itemData(index)
        if session_id:
            self._load_session_content(session_id)

    def _load_session_content(self, session_id: str):
        """加载指定会话的内容到聊天显示区域。"""
        if not self.session_manager:
            return
        session = self.session_manager.sessions.get(session_id)
        if session:
            self.session_manager.switch_session(session_id)
            self.chat_display.clear()
            for msg in session.messages:
                role = msg.get('role', 'system')
                content = msg.get('content', '')
                self._append_message(role, content)

    def _create_new_session(self):
        """创建新会话。"""
        if self.session_manager:
            self.session_manager.create_session()
            self._refresh_session_combo()
            self.chat_display.clear()

    def _clear_session(self):
        """清空当前会话。"""
        if self.session_manager:
            session = self.session_manager.get_active_session()
            if session:
                session.clear()
                self.chat_display.clear()
                self._append_message('system', '会话已清空。')

    def _refresh_session_combo(self):
        """
        刷新会话下拉框。

        刷新期间屏蔽信号，避免 clear()/addItem() 触发 currentIndexChanged
        级联加载错误会话；每项用 userData 绑定 session_id，不依赖索引顺序。
        """
        if not self.session_manager:
            return
        sessions = self.session_manager.list_sessions()
        self.session_combo.blockSignals(True)
        try:
            self.session_combo.clear()
            active_index = 0
            for i, s in enumerate(sessions):
                name = s['name']
                if s['message_count'] > 0:
                    name += f' ({s["message_count"]})'
                self.session_combo.addItem(name, userData=s['session_id'])
                if s.get('is_active'):
                    active_index = i
            if sessions:
                self.session_combo.setCurrentIndex(active_index)
        finally:
            self.session_combo.blockSignals(False)
