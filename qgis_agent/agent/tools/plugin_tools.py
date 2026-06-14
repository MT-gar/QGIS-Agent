# -*- coding: utf-8 -*-
"""
插件集成工具

提供与其他 QGIS 插件的集成能力：
- 通过 Python import 调用其他插件的 API
- 通过 Processing 框架调用 GRASS/SAGA 算法
- 通过 db_manager 管理数据库连接
- 通过自定义 Python 代码执行
"""

from typing import Optional, List, Dict


def list_installed_plugins() -> List[dict]:
    """
    列出所有已安装的 QGIS 插件。

    通过 QGIS 内部插件管理器获取已加载的插件列表。

    :return: 插件信息列表，每个元素包含 name、path、active 字段
    """
    iface = _get_iface()
    if iface is None:
        return []

    try:
        # 通过 QGIS 内部机制获取已加载插件
        from qgis.utils import plugins
        result = []
        for plugin_name, plugin_module in plugins.items():
            result.append({
                'name': plugin_name,
                'active': plugin_module is not None,
            })
        return result
    except Exception:
        pass

    # 回退：尝试通过 QCoreApplication 获取
    try:
        from qgis.core import QgsApplication
        # 获取插件路径下的目录名作为候选
        import os
        qgis_plugins_dir = os.path.join(
            os.path.dirname(__import__('qgis').__file__),
            'python', 'plugins'
        )
        if os.path.isdir(qgis_plugins_dir):
            result = []
            for entry in os.listdir(qgis_plugins_dir):
                if os.path.isdir(os.path.join(qgis_plugins_dir, entry)):
                    result.append({'name': entry, 'active': False})
            return result
    except Exception:
        pass

    return []


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
    """获取 QGIS 接口对象（延迟导入）。"""
    try:
        from qgis.utils import iface
        return iface
    except ImportError:
        return None
