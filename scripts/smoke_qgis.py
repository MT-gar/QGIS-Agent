# -*- coding: utf-8 -*-
"""
真实 QGIS 环境冒烟脚本（手动运行，非 pytest 用例）

在装有 QGIS 的机器上端到端验证工具层 API 是否可用。
不要命名为 test_*.py，避免被 pytest 当作单测在无 QGIS 的机器上误启动。

用法：
    python scripts/smoke_qgis.py
环境变量：
    QGIS_PREFIX  QGIS 安装根目录（默认 C:\\Program Files\\QGIS 4.0.3）
"""

import subprocess
import sys
import os

# 仓库根目录与插件目录（从本文件位置推导，不写死个人路径）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(REPO_ROOT, 'qgis_agent')

# QGIS 安装目录（允许通过环境变量覆盖）
QGIS_PREFIX = os.environ.get('QGIS_PREFIX', r'C:\Program Files\QGIS 4.0.3')


def _qp(*parts):
    """拼接 QGIS 安装目录下的子路径。"""
    return os.path.join(QGIS_PREFIX, *parts)


# 设置 DLL 搜索目录（Windows 10+）
if hasattr(os, 'add_dll_directory'):
    for d in [_qp('apps', 'qt6', 'bin'), _qp('bin'),
              _qp('apps', 'qgis', 'bin'), _qp('apps', 'qt6', 'lib')]:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass

os.environ.setdefault('PROJ_DATA', _qp('share', 'proj'))
os.environ.setdefault('PROJ_LIB', _qp('share', 'proj'))

os.environ['PATH'] = os.pathsep.join([
    _qp('apps', 'qt6', 'bin'), _qp('bin'),
    _qp('apps', 'qgis', 'bin'), _qp('apps', 'qt6', 'lib'),
    os.environ.get('PATH', ''),
])

env = os.environ.copy()
env['PYTHONPATH'] = os.pathsep.join([
    _qp('apps', 'qgis', 'python'),
    _qp('apps', 'qgis', 'python', 'plugins'),
    _qp('apps', 'python312'),
    _qp('apps', 'python312', 'Lib', 'site-packages'),
    PLUGIN_DIR,
])

# 在子进程中运行的测试代码（以 qgis_agent/ 为根，按 agent.* 导入）
test_code = f'''
import sys
sys.path.insert(0, r"{PLUGIN_DIR}")

# QGIS 独立运行的标准初始化：必须先设 prefix path，再构造 QgsApplication 实例，
# 最后才能 initQgis()。直接调 QgsApplication.initQgis() 会因应用对象为空而报
# "Application path not initialized"。
from qgis.core import QgsApplication
QgsApplication.setPrefixPath(r"{QGIS_PREFIX}\\apps\\qgis", True)
# 第二个参数 GUIenabled=False：无界面运行，避免依赖显示环境
qgs = QgsApplication([], False)
qgs.initQgis()
print("QGIS init OK")
print(f"prefix: {{QgsApplication.prefixPath()}}")

from qgis.core import QgsProject, QgsCoordinateReferenceSystem
crs = QgsCoordinateReferenceSystem("EPSG:4326")
print(f"CRS: {{crs.description()}}")

# qgis_bridge
from agent.tools.qgis_bridge import QGisAPIBridge
bridge = QGisAPIBridge()
bridge._discover_classes()
print(f"Bridge: {{len(bridge._core_classes)}} core classes")

# 工具模块导入冒烟（函数名与实际模块归属一一对应）
from agent.tools.iface_tools import list_layers, add_layer, take_screenshot
from agent.tools.processing_bridge import list_algorithms, run_algorithm
from agent.tools.layer_tools import save_layer_as, reproject_layer
from agent.tools.raster_tools import get_raster_stats
from agent.tools.expression_tools import calculate_field, evaluate_expression
from agent.tools.edit_tools import start_editing, add_feature
from agent.tools.network_tools import add_wms_layer, get_network_response
from agent.tools.layout_tools import create_layout, list_layouts
from agent.tools.plugin_tools import get_db_manager, execute_python_code
from agent.safety import SafetyGuard
print("all tool modules imported: OK")

# 初始化 Processing 框架（注册算法提供者）。
# 独立运行时不走 processing 插件的 Processing.initialize()（依赖 qgis.utils 的
# 插件导入钩子，常报 No module named 'processing.core'）；改为直接把原生算法
# 提供者注册进 processingRegistry，这是独立脚本注册 native: 算法的标准手段。
try:
    from qgis.analysis import QgsNativeAlgorithms
    QgsApplication.processingRegistry().addProvider(QgsNativeAlgorithms())
    print("native algorithm provider registered: OK")
except Exception as e:
    # 注册失败不致命：工具模块已导入成功，仅算法清单查询可能落空
    print(f"WARN: register native provider failed: {{e}}")

# Processing 算法可用性
algs = list_algorithms("native")
print(f"native algorithms providers: {{list(algs.keys())[:3]}}")

print("\\nSMOKE OK")
qgs.exitQgis()
'''

result = subprocess.run(
    [_qp('apps', 'python312', 'python.exe'), '-c', test_code],
    env=env,
    cwd=REPO_ROOT,
)
sys.exit(result.returncode)
