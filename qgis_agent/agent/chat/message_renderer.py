# -*- coding: utf-8 -*-
"""
消息渲染器

提供消息格式化功能：
- Markdown 粗体/斜体/代码块支持
- 表格渲染
- 纯 HTML 输出，适合 QTextEdit 显示
"""

import html
import re
from typing import List, Optional


def format_message(text: str) -> str:
    """
    格式化 Agent 消息，支持基础 Markdown 语法，输出安全的 HTML。

    先对全文做 HTML 转义（防注入），再用成对正则把 Markdown 标记转为
    HTML 标签：代码块（```）、行内代码（`code`）、粗体（**text**）、斜体（*text*）。

    :param text: 原始消息文本
    :return: 适合 QTextEdit 显示的安全 HTML
    """
    if not text:
        return ''

    # 1) 先转义，杜绝 <script>/<img onerror> 等被当作 HTML 执行
    escaped = html.escape(text)

    # 2) 代码块 ```lang\n...```（转义后反引号不受影响）
    def _code_block(m):
        body = m.group(1)
        # 去掉首行可能的语言标记
        lines = body.split('\n', 1)
        code = lines[1] if len(lines) > 1 else lines[0]
        code = code.strip('\n')
        style = ('background:#2d2d2d;color:#ccc;padding:8px;border-radius:4px;'
                 'font-family:Consolas;font-size:11px;')
        return f'<pre style="{style}">{code}</pre>'

    result = re.sub(r'```(.*?)```', _code_block, escaped, flags=re.DOTALL)

    # 3) 行内代码 `code`（成对匹配）
    result = re.sub(r'`([^`]+)`', r'<code>\1</code>', result)
    # 4) 粗体 **text**（非贪婪，成对匹配）
    result = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', result)
    # 5) 斜体 *text*（避免吃掉已处理的 ** —— 此处 ** 已被消费）
    result = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', result)

    return result


def format_table(data: List[list]) -> str:
    """
    将表格数据格式化为 ASCII 文本表格。

    :param data: 列表的列表，第一行为表头
    :return: 格式化后的表格字符串
    """
    if not data:
        return '(空数据)'

    # 计算每列宽度
    col_widths = [0] * len(data[0])
    for row in data:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    # 格式化表头
    header = ' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(data[0]))
    separator = '-+-'.join('-' * w for w in col_widths)

    # 格式化数据行
    rows = []
    for row in data[1:]:
        rows.append(' | '.join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

    return '\n'.join([header, separator] + rows)
