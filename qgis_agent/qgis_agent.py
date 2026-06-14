# -*- coding: utf-8 -*-
"""
QGIS Agent 主入口

此文件是 Agent 逻辑的总入口。
在插件加载时由 plugin.py 调用，或在 standalone 模式下直接运行。
"""

import sys
import os


def main():
    """
    独立运行模式的主入口。

    用于在没有 QGIS 的情况下测试 Agent 核心逻辑。
    """
    print('=== QGIS Agent ===')
    print('此插件需要在 QGIS 中运行。')
    print('请通过 QGIS 插件管理器安装并加载。')
    print()
    # 使用原始字符串，避免 \U \u 等被解释为 Unicode 转义导致 SyntaxError
    print(r'项目: C:\文件\项目\QGIS Agent/qgis_agent/')


if __name__ == '__main__':
    main()
