# -*- coding: utf-8 -*-
"""
QGIS Agent - AI 驱动的 QGIS 自动化插件

使 AI agent 能自由调用 QGIS 中的所有功能。
支持图层管理、Processing 算法(1500+)、要素编辑、打印布局等。
"""

__version__ = '0.1.0'


def classFactory(iface):
    """
    QGIS 插件入口函数。

    QGIS 以插件目录名（qgis_agent）作为顶级包导入本插件，因此包内统一使用
    相对导入即可，无需任何 sys.path 注入。

    :param iface: QGIS 接口对象 (QgisInterface)
    :return: 插件主类实例
    """
    # 使用相对导入加载主插件类（依赖 QGIS 以 qgis_agent 包名加载本插件）
    from .plugin import QgisAgent
    return QgisAgent(iface)
