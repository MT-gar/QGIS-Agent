# -*- coding: utf-8 -*-
"""
QGIS Agent 打包脚本

将插件打包为 .zip 文件，可直接通过 QGIS 插件管理器安装。

用法：
    python pack.py                    # 打包到 dist/qgis-agent.zip
    python pack.py --output my-plugin.zip
"""

import os
import sys
import fnmatch
import zipfile
import argparse
from pathlib import Path


def get_plugin_root():
    """获取插件根目录。"""
    return Path(__file__).parent


def get_exclusions():
    """
    获取需要排除的文件/目录名与通配符模式。

    既包含精确目录名，也包含通配符（由 should_exclude 用 fnmatch 匹配），
    并排除凭据与开发文件，避免误打进发布包。
    """
    return {
        # 目录/精确名
        '__pycache__',
        '.git',
        '.gitignore',
        '.claude',
        'tasks',
        'docs',
        'dist',
        '.DS_Store',
        'Thumbs.db',
        # 开发脚本（不应进入发布包）
        'pack.py',
        'diagnose.py',
        # 通配符模式
        '*.pyc',
        '*.pyo',
        '*.log',
        '*.db',
        'test_*.py',
        '*_test.py',
        # 凭据/敏感文件
        '.env',
        '*.key',
        '*.pem',
        'secrets*',
    }


def should_exclude(file_path: Path, exclusions: set) -> bool:
    """
    判断文件是否应被排除。

    对路径的每一段，既做精确名匹配，也用 fnmatch 做通配符匹配
    （修复旧实现 '*.pyc' 这类通配符永远匹配不到的问题）。
    """
    for part in file_path.parts:
        for pattern in exclusions:
            if part == pattern or fnmatch.fnmatch(part, pattern):
                return True
    return False


def pack_plugin(output_path: str = None):
    """
    打包 QGIS Agent 插件为 .zip 文件。

    :param output_path: 输出路径（默认 dist/qgis-agent.zip）
    """
    plugin_root = get_plugin_root()

    if output_path is None:
        dist_dir = plugin_root / 'dist'
        dist_dir.mkdir(exist_ok=True)
        output_path = str(dist_dir / 'qgis-agent.zip')

    exclusions = get_exclusions()

    print(f"=== QGIS Agent 打包 ===")
    print(f"插件根目录: {plugin_root}")
    print(f"输出文件: {output_path}")

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(plugin_root):
            # 跳过排除的目录
            dirs[:] = [d for d in dirs if d not in exclusions]

            for filename in files:
                file_path = Path(root) / filename

                # 跳过排除的文件
                if should_exclude(file_path.relative_to(plugin_root), exclusions):
                    continue

                # QGIS 插件 ZIP 需要一个顶层插件目录，例如 qgis_agent/metadata.txt
                arcname = str(Path(plugin_root.name) / file_path.relative_to(plugin_root))
                zf.write(file_path, arcname)

                file_count += 1
                total_size += file_path.stat().st_size

    print(f"\n打包完成!")
    print(f"  文件数: {file_count}")
    print(f"  大小: {total_size / 1024:.1f} KB")
    print(f"  输出: {output_path}")
    print(f"\n安装方式:")
    print(f"  1. 在 QGIS 中: 插件 → 管理并安装插件 → 从 ZIP 安装")
    print(f"  2. 选择: {output_path}")
    print(f"  3. 重启 QGIS 或在插件管理器中启用")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='打包 QGIS Agent 插件')
    parser.add_argument('--output', '-o', help='输出文件路径')
    args = parser.parse_args()

    pack_plugin(args.output)
