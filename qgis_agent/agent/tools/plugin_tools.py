# -*- coding: utf-8 -*-
"""
插件集成工具

提供与其他 QGIS 插件的集成能力：
- 搜索远程插件仓库（plugins.qgis.org）
- 下载并安装插件
- 启用 / 禁用已安装插件
- 列出已安装插件（含 metadata 详情）
- 通过 Python import 调用其他插件的 API
- 通过 Processing 框架调用 GRASS/SAGA 算法
- 通过 db_manager 管理数据库连接
- 通过自定义 Python 代码执行
"""

import io
import os
import zipfile
import configparser
import xml.etree.ElementTree as ET
from typing import Optional, List, Dict

# 版本兼容性
try:
    from ..compat import (
        QGIS_VERSION_INT, get_plugin_dirs, safe_process_events,
        has_network_access_manager, qgis_version_at_least,
    )
except ImportError:
    # 非 QGIS 环境（如单元测试）
    QGIS_VERSION_INT = 0
    get_plugin_dirs = lambda: []
    safe_process_events = lambda: None
    has_network_access_manager = lambda: False
    qgis_version_at_least = lambda *a: False

# ── 常量 ──────────────────────────────────────────────────
REPO_URL = 'https://plugins.qgis.org/plugins/plugins.xml'


# ======================================================================
#  任务计划控制（供 Agent 循环调用）
# ======================================================================

def pause_plan(reason: str = '用户请求暂停') -> str:
    """
    暂停当前任务计划的执行。

    :param reason: 暂停原因
    :return: 确认消息
    """
    return f'任务计划已暂停。原因: {reason}'


def skip_step(reason: str = '') -> str:
    """
    跳过当前任务计划中正在执行的步骤。

    :param reason: 跳过原因
    :return: 确认消息
    """
    return f'已跳过当前步骤。原因: {reason}' if reason else '已跳过当前步骤。'


# ======================================================================
#  插件仓库搜索
# ======================================================================

def search_plugins(query: str = '', category: str = '',
                   limit: int = 10, experimental: bool = False) -> List[dict]:
    """
    搜索 QGIS 官方插件仓库。

    通过 plugins.qgis.org 的 plugins.xml 获取全部插件元数据，
    按关键词和分类过滤后返回匹配结果。

    :param query: 搜索关键词（匹配 name / description / tags，不区分大小写）
    :param category: 分类过滤（Analysis / Database / Raster / Vector / Web / Processing 等）
    :param limit: 返回结果数量上限
    :param experimental: 是否包含实验性插件
    :return: 插件信息列表
    """
    try:
        xml_text = _fetch_repo_xml()
        if not xml_text:
            return []
        plugins = _parse_plugins_xml(xml_text)
    except Exception as e:
        return [{'error': f'获取插件仓库失败: {e}'}]

    # 过滤
    q_lower = query.lower()
    results = []
    for p in plugins:
        # 实验性插件过滤
        if not experimental and p.get('experimental', '').lower() == 'true':
            continue
        # 分类过滤
        if category and category.lower() not in (p.get('category', '')).lower():
            continue
        # 关键词匹配（name / description / tags）
        if q_lower:
            searchable = ' '.join([
                p.get('name', ''),
                p.get('description', ''),
                p.get('tags', ''),
            ]).lower()
            if q_lower not in searchable:
                continue
        results.append(p)

    # 按下载量排序（降序）
    results.sort(key=lambda x: int(x.get('downloads', '0') or '0'), reverse=True)
    return results[:limit]


def get_plugin_info(plugin_id: str) -> dict:
    """
    获取指定插件的详细信息。

    :param plugin_id: 插件标识符（name 字段）
    :return: 插件详情字典
    """
    try:
        xml_text = _fetch_repo_xml()
        if not xml_text:
            return {'error': '无法获取插件仓库'}
        plugins = _parse_plugins_xml(xml_text)
    except Exception as e:
        return {'error': f'获取插件仓库失败: {e}'}

    for p in plugins:
        if p.get('name', '').lower() == plugin_id.lower():
            return p
    return {'error': f'未找到插件: {plugin_id}'}


# ======================================================================
#  插件安装 / 卸载
# ======================================================================

def install_plugin(plugin_id: str, version: str = '',
                   enable: bool = True) -> dict:
    """
    从官方仓库下载并安装指定插件。

    流程：获取 download_url → 下载 ZIP → 解压到用户插件目录 → 注册 → 可选启用。

    :param plugin_id: 插件标识符（name 字段）
    :param version: 指定版本（留空则安装最新版）
    :param enable: 安装后是否自动启用
    :return: 安装结果
    """
    # 1. 从仓库获取插件信息
    info = get_plugin_info(plugin_id)
    if 'error' in info:
        return info

    # 版本匹配
    if version and info.get('version', '') != version:
        return {
            'error': f'版本不匹配: 仓库中最新版本为 {info.get("version")}',
            'available_version': info.get('version'),
        }

    download_url = info.get('download_url', '')
    if not download_url:
        return {'error': f'插件 {plugin_id} 没有下载链接'}

    # 2. 确定安装目录
    plugins_dir = _user_plugins_dir()
    if not plugins_dir:
        return {'error': '无法确定用户插件目录'}

    target_dir = os.path.join(plugins_dir, plugin_id)

    # 3. 如果已安装，先卸载旧版
    if os.path.isdir(target_dir):
        try:
            import shutil
            shutil.rmtree(target_dir)
        except Exception as e:
            return {'error': f'无法移除旧版本: {e}'}

    # 4. 下载 ZIP
    try:
        zip_data = _download_file(download_url)
        if not zip_data:
            return {'error': '下载插件失败'}
    except Exception as e:
        return {'error': f'下载失败: {e}'}

    # 5. 解压
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_data))
        zf.extractall(plugins_dir)
        zf.close()
    except Exception as e:
        return {'error': f'解压失败: {e}'}

    # 6. 注册到 QGIS
    try:
        import qgis.utils
        qgis.utils.updateAvailablePlugins()
    except Exception:
        pass

    # 7. 可选启用
    enabled = False
    if enable:
        enabled = enable_plugin(plugin_id).get('success', False)

    return {
        'success': True,
        'plugin_id': plugin_id,
        'version': info.get('version', ''),
        'installed_path': target_dir,
        'enabled': enabled,
        'message': f'插件 {plugin_id} 安装成功' + ('（已启用）' if enabled else ''),
    }


def uninstall_plugin(plugin_id: str) -> dict:
    """
    卸载指定插件。

    先禁用，再删除插件目录。

    :param plugin_id: 插件标识符
    :return: 卸载结果
    """
    plugins_dir = _user_plugins_dir()
    if not plugins_dir:
        return {'error': '无法确定用户插件目录'}

    target_dir = os.path.join(plugins_dir, plugin_id)
    if not os.path.isdir(target_dir):
        return {'error': f'插件 {plugin_id} 未安装'}

    # 先禁用
    try:
        disable_plugin(plugin_id)
    except Exception:
        pass

    # 删除目录
    try:
        import shutil
        shutil.rmtree(target_dir)
        return {
            'success': True,
            'plugin_id': plugin_id,
            'message': f'插件 {plugin_id} 已卸载',
        }
    except Exception as e:
        return {'error': f'卸载失败: {e}'}


# ======================================================================
#  插件启用 / 禁用
# ======================================================================

def enable_plugin(plugin_id: str) -> dict:
    """
    启用已安装的插件。

    调用 qgis.utils.loadPlugin + startPlugin。

    :param plugin_id: 插件标识符
    :return: 操作结果
    """
    try:
        import qgis.utils

        # 已经激活
        if plugin_id in qgis.utils.active_plugins:
            return {
                'success': True,
                'plugin_id': plugin_id,
                'message': f'插件 {plugin_id} 已经处于启用状态',
            }

        # 确保已发现
        qgis.utils.updateAvailablePlugins()

        # 加载模块
        if plugin_id not in qgis.utils.available_plugins:
            return {'error': f'插件 {plugin_id} 未安装或不可用'}

        loaded = qgis.utils.loadPlugin(plugin_id)
        if not loaded:
            return {'error': f'加载插件 {plugin_id} 失败'}

        started = qgis.utils.startPlugin(plugin_id)
        if not started:
            return {'error': f'启动插件 {plugin_id} 失败'}

        return {
            'success': True,
            'plugin_id': plugin_id,
            'message': f'插件 {plugin_id} 已启用',
        }
    except Exception as e:
        return {'error': f'启用插件失败: {e}'}


def disable_plugin(plugin_id: str) -> dict:
    """
    禁用已启用的插件。

    :param plugin_id: 插件标识符
    :return: 操作结果
    """
    try:
        import qgis.utils

        if plugin_id not in qgis.utils.active_plugins:
            return {
                'success': True,
                'plugin_id': plugin_id,
                'message': f'插件 {plugin_id} 未启用',
            }

        qgis.utils.unloadPlugin(plugin_id)
        return {
            'success': True,
            'plugin_id': plugin_id,
            'message': f'插件 {plugin_id} 已禁用',
        }
    except Exception as e:
        return {'error': f'禁用插件失败: {e}'}


# ======================================================================
#  已安装插件列表（增强版）
# ======================================================================

def list_installed_plugins(enabled_only: bool = False) -> List[dict]:
    """
    列出所有已安装的 QGIS 插件（含 metadata 详情）。

    同时返回 active（已启用）和 available（已安装未启用）的插件，
    并读取 metadata.txt 获取版本、作者等信息。

    :param enabled_only: 是否只返回已启用的插件
    :return: 插件信息列表
    """
    try:
        import qgis.utils

        active = set(getattr(qgis.utils, 'active_plugins', []))
        available = set(getattr(qgis.utils, 'available_plugins', []))

        if enabled_only:
            names = active
        else:
            names = active | available

        results = []
        for name in sorted(names):
            entry = {
                'name': name,
                'enabled': name in active,
            }
            # 读取 metadata.txt
            meta = _read_plugin_metadata(name)
            if meta:
                entry.update(meta)
            results.append(entry)
        return results

    except Exception:
        # 回退：扫描目录
        return _list_plugins_from_dir(enabled_only)


# ======================================================================
#  调用已安装插件的功能
# ======================================================================

def call_plugin_method(plugin_id: str, method_name: str,
                       args_json: str = '[]') -> dict:
    """
    调用已启用插件实例上的指定方法。

    插件必须已启用（在 qgis.utils.plugins 中有注册）。
    用于 Agent 自动调用插件暴露的公开 API。

    :param plugin_id: 插件标识符
    :param method_name: 要调用的方法名
    :param args_json: 参数列表的 JSON 字符串，如 '[1, 2]' 或 '{"key": "value"}'
    :return: 方法调用结果
    """
    import json as _json

    try:
        import qgis.utils

        if plugin_id not in qgis.utils.active_plugins:
            return {
                'error': f'插件 {plugin_id} 未启用',
                'hint': f'请先调用 enable_plugin("{plugin_id}")',
            }

        plugin_instance = qgis.utils.plugins.get(plugin_id)
        if plugin_instance is None:
            return {'error': f'无法获取插件 {plugin_id} 的实例'}

        method = getattr(plugin_instance, method_name, None)
        if method is None:
            available = [m for m in dir(plugin_instance)
                         if not m.startswith('_') and callable(getattr(plugin_instance, m, None))]
            return {
                'error': f'插件 {plugin_id} 没有方法 {method_name}',
                'available_methods': available[:20],
            }

        # 解析参数
        try:
            parsed = _json.loads(args_json) if args_json else []
        except _json.JSONDecodeError:
            return {'error': f'args_json 不是有效的 JSON: {args_json}'}

        if isinstance(parsed, list):
            result = method(*parsed)
        elif isinstance(parsed, dict):
            result = method(**parsed)
        else:
            result = method(parsed)

        return {
            'success': True,
            'plugin_id': plugin_id,
            'method': method_name,
            'result': _safe_repr(result),
        }
    except Exception as e:
        return {'error': f'调用插件方法失败: {e}'}


# ======================================================================
#  内部辅助函数
# ======================================================================

def _fetch_repo_xml() -> str:
    """从 plugins.qgis.org 获取 plugins.xml 内容（兼容 QGIS 3.44+）。"""
    # 优先使用 QgsNetworkAccessManager（尊重代理/认证配置）
    if has_network_access_manager():
        try:
            from qgis.core import QgsNetworkAccessManager
            from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
            from qgis.PyQt.QtNetwork import QNetworkRequest

            request = QNetworkRequest(QUrl(REPO_URL))
            manager = QgsNetworkAccessManager.instance()
            reply = manager.get(request)

            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(30000)
            loop.exec()

            if not reply.isFinished():
                reply.abort()
                reply.deleteLater()
                return ''

            if reply.error() != reply.NetworkError.NoError:
                reply.deleteLater()
                return ''

            data = reply.readAll().data().decode('utf-8', errors='replace')
            reply.deleteLater()
            return data
        except Exception:
            pass

    # 回退：使用 Python requests
    try:
        import requests
        resp = requests.get(REPO_URL, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception:
        return ''


def _parse_plugins_xml(xml_text: str) -> List[dict]:
    """解析 plugins.xml，返回插件信息列表。"""
    plugins = []
    try:
        root = ET.fromstring(xml_text)
        for elem in root.findall('pyqgis_plugin'):
            p = {
                'name': elem.get('name', ''),
                'version': elem.get('version', ''),
            }
            # 读取所有子元素
            for child in elem:
                tag = child.tag
                text = (child.text or '').strip()
                if tag and text:
                    p[tag] = text
            plugins.append(p)
    except ET.ParseError:
        pass
    return plugins


def _download_file(url: str) -> bytes:
    """下载文件内容（兼容 QGIS 3.44+）。"""
    # 优先 QgsNetworkAccessManager
    if has_network_access_manager():
        try:
            from qgis.core import QgsNetworkAccessManager
            from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
            from qgis.PyQt.QtNetwork import QNetworkRequest

            request = QNetworkRequest(QUrl(url))
            manager = QgsNetworkAccessManager.instance()
            reply = manager.get(request)

            loop = QEventLoop()
            reply.finished.connect(loop.quit)
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(60000)
            loop.exec()

            if not reply.isFinished():
                reply.abort()
                reply.deleteLater()
                return b''

            if reply.error() != reply.NetworkError.NoError:
                reply.deleteLater()
                return b''

            data = reply.readAll().data()
            reply.deleteLater()
            return data
        except Exception:
            pass

    # 回退
    try:
        import requests
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.content
    except Exception:
        return b''


def _user_plugins_dir() -> str:
    """获取当前用户插件目录（兼容 QGIS 3.44+）。"""
    # 优先使用兼容性模块
    dirs = get_plugin_dirs()
    if dirs:
        return dirs[0]

    # 回退：直接调用 API
    try:
        from qgis.core import QgsApplication
        return os.path.join(
            QgsApplication.qgisSettingsDirPath(), 'python', 'plugins'
        )
    except Exception:
        pass

    # 再回退：通过 qgis 模块路径推导
    try:
        import qgis
        qgis_dir = os.path.dirname(qgis.__file__)
        return os.path.join(qgis_dir, 'python', 'plugins')
    except Exception:
        return ''


def _read_plugin_metadata(plugin_id: str) -> dict:
    """读取已安装插件的 metadata.txt。"""
    plugins_dir = _user_plugins_dir()
    if not plugins_dir:
        return {}

    meta_path = os.path.join(plugins_dir, plugin_id, 'metadata.txt')
    if not os.path.isfile(meta_path):
        return {}

    try:
        config = configparser.ConfigParser()
        config.read(meta_path, encoding='utf-8')
        if not config.has_section('general'):
            return {}

        fields = [
            'name', 'description', 'version', 'author', 'email',
            'about', 'category', 'tags', 'homepage', 'repository',
            'qgisMinimumVersion', 'qgisMaximumVersion',
            'experimental', 'deprecated', 'hasProcessingProvider',
        ]
        result = {}
        for f in fields:
            val = config.get('general', f, fallback='')
            if val:
                result[f] = val
        return result
    except Exception:
        return {}


def _list_plugins_from_dir(enabled_only: bool) -> List[dict]:
    """回退方案：扫描目录获取插件列表。"""
    plugins_dir = _user_plugins_dir()
    if not plugins_dir or not os.path.isdir(plugins_dir):
        return []

    results = []
    for entry in os.listdir(plugins_dir):
        entry_path = os.path.join(plugins_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        if not os.path.isfile(os.path.join(entry_path, '__init__.py')):
            continue

        info = {'name': entry, 'enabled': False}
        meta = _read_plugin_metadata(entry)
        if meta:
            info.update(meta)
        if not enabled_only or info.get('enabled'):
            results.append(info)
    return results


def get_db_manager() -> dict:
    """
    获取 db_manager 插件的引用。

    通过 Python import 获取 db_manager 模块。
    允许 Agent 直接调用数据库管理功能。

    :return: db_manager 模块或错误信息
    """
    try:
        import sys
        import os
        import qgis

        # 从 qgis.__file__ 动态推导插件目录，不写死任何机器绝对路径
        qgis_dir = os.path.dirname(qgis.__file__)
        plugins_path = os.path.join(qgis_dir, 'python', 'plugins')
        if os.path.isdir(plugins_path) and plugins_path not in sys.path:
            sys.path.insert(0, plugins_path)

        import db_manager.db_manager as dbm  # noqa: F401
        return {
            'success': True,
            'module': 'db_manager',
            'available': True,
            'message': 'db_manager 可用，可通过 qgis_api_call 调用其 API',
        }
    except ImportError as e:
        return {
            'success': False,
            'error': f'无法导入 db_manager: {str(e)}',
            'hint': '确保 QGIS 安装中包含 db_manager 插件',
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
        }


def run_grass_algorithm(module: str, parameters: dict) -> dict:
    """
    执行 GRASS 算法。

    GRASS GIS 8.4 提供了 700+ 个 GIS 工具。
    通过 Processing 框架执行 GRASS 算法。

    :param module: GRASS 模块名（如 'r.buffer', 'v.buffer'）
    :param parameters: 模块参数
    :return: 操作结果
    """
    try:
        from qgis import processing

        # GRASS provider 前缀为 grass:（旧版 grass7:），模块名含点（如 v.buffer）保持原样。
        # 直接透传调用方提供的全部参数，不再写死 input/distance/output。
        algorithm_id = f'grass:{module}'
        result = processing.run(algorithm_id, dict(parameters or {}))
        return {
            'success': True,
            'algorithm': algorithm_id,
            'output': result,
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'GRASS 算法执行失败: {str(e)}',
            'hint': '确保 GRASS 已正确配置；module 形如 v.buffer / r.buffer',
        }


def execute_python_code(code: str, globals_dict: Optional[dict] = None) -> dict:
    """
    执行自定义 Python 代码（通过 QGIS API）。

    这是最强大也最危险的工具——可编写任意 Python 脚本操作 QGIS。

    安全说明：本函数**不是沙箱**。下方提供的 builtins 白名单仅为便利，
    并不能真正阻止逃逸（通过 getattr 链等手段仍可访问任意对象）。真正的
    安全边界是 Agent 循环在执行本工具前的"危险操作确认弹窗"——由用户决定
    是否放行。因此这里专注于"把代码跑起来并把结果回传给 LLM"。

    约定：脚本中可向名为 `result` 的变量赋值作为返回结果；同时捕获 stdout。

    :param code: Python 代码字符串
    :param globals_dict: 额外注入的全局变量字典（可选）
    :return: 执行结果（含 stdout 与 result 变量）
    """
    import io
    import sys as _sys
    from contextlib import redirect_stdout

    try:
        # 注入常用 QGIS 对象，并提供完整 builtins（不伪装沙箱）
        env = {'__builtins__': __builtins__}
        try:
            import qgis.core
            from qgis.utils import iface
            env['QgsApplication'] = qgis.core.QgsApplication
            env['QgsProject'] = qgis.core.QgsProject
            env['QgsVectorLayer'] = qgis.core.QgsVectorLayer
            env['QgsRasterLayer'] = qgis.core.QgsRasterLayer
            env['QgsGeometry'] = qgis.core.QgsGeometry
            env['QgsPointXY'] = qgis.core.QgsPointXY
            env['QgsCoordinateReferenceSystem'] = qgis.core.QgsCoordinateReferenceSystem
            env['QgsRectangle'] = qgis.core.QgsRectangle
            env['QgsProcessingFeedback'] = qgis.core.QgsProcessingFeedback
            env['iface'] = iface
            from qgis import processing as _processing
            env['processing'] = _processing
        except Exception as e:
            env['_qgis_error'] = str(e)

        if globals_dict:
            env.update(globals_dict)

        # 捕获标准输出，并约定 result 变量作为返回值
        buf = io.StringIO()
        with redirect_stdout(buf):
            exec(code, env)

        stdout = buf.getvalue()
        result_value = env.get('result')

        return {
            'success': True,
            'stdout': stdout[:10000],
            'result': _safe_repr(result_value),
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'代码执行失败: {str(e)}',
            'code_snippet': code[:200],
        }


def _safe_repr(value) -> Optional[str]:
    """将 result 变量安全地转为字符串（None 时返回 None）。"""
    if value is None:
        return None
    try:
        return str(value)[:5000]
    except Exception:
        return '<无法转换的结果对象>'


def _get_iface():
    """获取 QGIS 接口对象（兼容 QGIS 3.44+）。"""
    try:
        from ..compat import get_iface
        return get_iface()
    except ImportError:
        try:
            from qgis.utils import iface
            return iface
        except ImportError:
            return None
