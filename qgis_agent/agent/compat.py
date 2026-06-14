# -*- coding: utf-8 -*-
"""
QGIS 版本兼容性层

提供统一的版本检测和 API 兼容性包装，确保插件在 QGIS 3.44+ 上正常运行。

主要功能：
- 版本检测（QGIS_VERSION_INT, QGIS_VERSION_STR）
- 兼容性包装函数（处理不同版本的 API 差异）
- 特性检测（检查特定 API 是否可用）
"""

import os
from typing import Optional, Tuple

# ── 版本常量 ──────────────────────────────────────────────────

# QGIS 版本整数格式：主版本*10000 + 次版本*100 + 修订版本
# 例如：3.44.0 = 34400, 3.22.0 = 32200, 3.28.0 = 32800
QGIS_VERSION_INT: int = 0
QGIS_VERSION_STR: str = 'unknown'
QGIS_VERSION_TUPLE: Tuple[int, ...] = (0, 0, 0)

try:
    from qgis.core import Qgis
    QGIS_VERSION_INT = Qgis.versionInt()
    QGIS_VERSION_STR = Qgis.version()
    # 解析版本元组
    parts = QGIS_VERSION_STR.split('.')
    QGIS_VERSION_TUPLE = tuple(int(p) for p in parts[:3]) if len(parts) >= 3 else (0, 0, 0)
except Exception:
    # 非 QGIS 环境（如单元测试）
    pass


# ── 版本比较 ──────────────────────────────────────────────────

def qgis_version_at_least(major: int, minor: int = 0, patch: int = 0) -> bool:
    """
    检查当前 QGIS 版本是否 >= 指定版本。

    :param major: 主版本号
    :param minor: 次版本号
    :param patch: 修订版本号
    :return: 是否满足版本要求
    """
    target = major * 10000 + minor * 100 + patch
    return QGIS_VERSION_INT >= target


def is_qgis_344() -> bool:
    """检查是否为 QGIS 3.44.x。"""
    return QGIS_VERSION_TUPLE[0] == 3 and QGIS_VERSION_TUPLE[1] == 44


def is_qgis_322_or_later() -> bool:
    """检查是否为 QGIS 3.22+（LTS 版本）。"""
    return qgis_version_at_least(3, 22)


def is_qgis_328_or_later() -> bool:
    """检查是否为 QGIS 3.28+（LTR 版本）。"""
    return qgis_version_at_least(3, 28)


# ── 兼容性包装函数 ──────────────────────────────────────────

def get_layer_by_name(name: str):
    """
    按名称获取图层（兼容 QGIS 3.44+）。

    QGIS 3.22+ 使用 QgsProject.instance().mapLayersByName()，
    3.44 也支持，但提供回退方案以防万一。

    :param name: 图层名称
    :return: 图层列表
    """
    try:
        from qgis.core import QgsProject
        return QgsProject.instance().mapLayersByName(name)
    except Exception:
        # 回退：遍历所有图层
        try:
            from qgis.core import QgsProject
            layers = QgsProject.instance().mapLayers().values()
            return [l for l in layers if l.name() == name]
        except Exception:
            return []


def get_plugin_dirs() -> list:
    """
    获取插件目录列表（兼容不同版本）。

    :return: 插件目录路径列表
    """
    dirs = []

    # 用户插件目录
    try:
        from qgis.core import QgsApplication
        user_dir = os.path.join(
            QgsApplication.qgisSettingsDirPath(), 'python', 'plugins'
        )
        if os.path.isdir(user_dir):
            dirs.append(user_dir)
    except Exception:
        pass

    # 系统插件目录
    try:
        import qgis
        qgis_dir = os.path.dirname(qgis.__file__)
        sys_dir = os.path.join(qgis_dir, 'python', 'plugins')
        if os.path.isdir(sys_dir):
            dirs.append(sys_dir)
    except Exception:
        pass

    return dirs


def get_iface():
    """
    获取 QGIS iface 对象（兼容不同版本）。

    :return: iface 对象或 None
    """
    try:
        from qgis.utils import iface
        return iface
    except ImportError:
        return None


def safe_process_events():
    """
    安全地处理 Qt 事件（兼容无 Qt 环境）。

    在 QGIS 3.44+ 中，QApplication.processEvents() 用于保持 UI 响应。
    """
    try:
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.processEvents()
    except Exception:
        pass


def safe_sleep_ms(ms: int):
    """
    安全地休眠（兼容无 Qt 环境）。

    :param ms: 休眠时间（毫秒）
    """
    try:
        from qgis.PyQt.QtCore import QThread
        QThread.msleep(ms)
    except Exception:
        import time
        time.sleep(ms / 1000.0)


# ── 特性检测 ──────────────────────────────────────────────────

def has_processing_provider() -> bool:
    """检查 Processing 框架是否可用。"""
    try:
        from qgis import processing
        return True
    except ImportError:
        return False


def has_network_access_manager() -> bool:
    """检查 QgsNetworkAccessManager 是否可用。"""
    try:
        from qgis.core import QgsNetworkAccessManager
        return True
    except ImportError:
        return False


def has_pyqt5() -> bool:
    """检查 PyQt5 是否可用。"""
    try:
        from PyQt5.QtCore import QObject
        return True
    except ImportError:
        return False


def has_pyqt6() -> bool:
    """检查 PyQt6 是否可用。"""
    try:
        from PyQt6.QtCore import QObject
        return True
    except ImportError:
        return False


# ── 版本信息 ──────────────────────────────────────────────────

def get_version_info() -> dict:
    """
    获取 QGIS 版本信息。

    :return: 版本信息字典
    """
    return {
        'qgis_version_int': QGIS_VERSION_INT,
        'qgis_version_str': QGIS_VERSION_STR,
        'qgis_version_tuple': QGIS_VERSION_TUPLE,
        'is_344': is_qgis_344(),
        'is_322_or_later': is_qgis_322_or_later(),
        'is_328_or_later': is_qgis_328_or_later(),
        'has_processing': has_processing_provider(),
        'has_network': has_network_access_manager(),
    }
