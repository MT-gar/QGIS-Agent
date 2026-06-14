# -*- coding: utf-8 -*-
"""
QGIS Agent 插件入口

这是 QGIS Agent 插件的主入口文件。QGIS 在加载插件时会调用 __init__.py
中的 classFactory() 函数来获取插件类，然后实例化并调用其 __init__ 和
initGui 方法。

插件是普通的 QGIS Python GUI 插件类（不继承任何处理框架基类），
所有 GUI 操作通过 iface 接口完成。
"""

import os
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtCore import Qt


class QgisAgent:
    """
    QGIS Agent 主插件类。

    负责插件的初始化、UI 创建和生命周期管理。
    QGIS GUI 插件是普通 Python 对象，通过 classFactory 实例化，
    QGIS 依次调用其 initGui()（加载时）和 unload()（卸载时）。
    """

    def __init__(self, iface):
        """
        初始化插件。

        :param iface: QGIS 接口对象 (QgisInterface)
                      提供对地图画布、图层树、消息栏等全部 QGIS 功能的访问
        """
        # 保存 iface 引用，所有 QGIS GUI 操作通过 iface 进行
        self.iface = iface
        # 插件菜单名称（显示在 QGIS 菜单栏中）
        self.menu_name = 'QGIS Agent'
        # QAction 引用（用于菜单和工具栏）
        self.action = None
        # Agent 面板引用（懒加载）
        self.panel = None

    def initGui(self):
        """
        在 QGIS 启动或插件加载时执行的 GUI 初始化。

        创建 QAction、添加到工具栏和插件菜单。
        与 unload() 严格对称，确保卸载时能完整清理。
        """
        # 创建 QAction
        self.action = QAction(
            self._load_icon(),
            '打开 Agent 面板',
            self.iface.mainWindow(),
        )
        self.action.setObjectName('QgisAgentAction')
        self.action.setToolTip('打开 QGIS Agent 聊天面板')
        self.action.triggered.connect(self._toggle_panel)

        # 添加到插件菜单栏
        self.iface.pluginMenu().addAction(self.action)
        # 添加到工具栏
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """
        插件卸载时执行。

        清理资源：移除菜单项、工具栏按钮、销毁面板。
        所有移除操作与 initGui() 严格对称。
        """
        # 销毁 Agent 面板（dock 已被主窗口接管，必须 removeDockWidget 后再删除）
        if self.panel is not None:
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None

        if self.action is not None:
            # 与 initGui 对称地移除菜单项与工具栏按钮
            self.iface.pluginMenu().removeAction(self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def _load_icon(self) -> QIcon:
        """
        加载插件图标。

        :return: 图标对象（图标不存在时返回空 QIcon）
        """
        # 图标路径：插件目录下的 icons/agent.svg
        icon_path = os.path.join(
            os.path.dirname(__file__), 'icons', 'agent.svg'
        )
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        # 如果图标不存在，返回默认图标
        return QIcon()

    def _toggle_panel(self):
        """
        切换 Agent 面板的显示/隐藏。

        如果面板已创建则切换可见性，否则先创建再显示。
        面板以停靠窗口（Dock Widget）形式嵌入 QGIS 界面。
        """
        if self.panel is None:
            self._create_panel()

        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.show()
            self.panel.raise_()

    def _create_panel(self):
        """
        创建 Agent 聊天面板。

        面板继承 QgsDockWidget，嵌入 QGIS 界面右侧的停靠窗口区域。
        """
        # 延迟导入，避免插件加载时就拉起全部依赖
        from .agent.chat.chat_panel import ChatPanel

        # 创建停靠窗口面板
        self.panel = ChatPanel(
            self.iface,
            title=self.menu_name,
        )
        # 添加为停靠窗口（右侧）
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
