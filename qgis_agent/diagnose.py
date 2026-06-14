# -*- coding: utf-8 -*-
"""
QGIS Agent 安装诊断脚本

在 QGIS 外部运行，验证插件的导入链是否正常。
也可以粘贴到 QGIS Python 控制台中运行，查看详细的诊断信息。

用法：
    python diagnose.py

提示：在 QGIS 外部运行时，QGIS/LangChain 模块导入会失败是正常的。
关键看 classFactory 的导入测试是否能通过。
"""

import sys
import os
from pathlib import Path

# ============================================================
# 配置：指向插件目录
# ============================================================
plugin_root = Path(__file__).resolve().parent / "qgis_agent"
qgis_plugin_dir = Path(
    r"C:\Users\z_mt0\AppData\Roaming\QGIS\QGIS4\profiles\default\python\plugins"
)
installed_plugin = qgis_plugin_dir / "qgis_agent"

if installed_plugin.exists():
    test_dir = installed_plugin
    print(f"[INFO] 使用已安装的插件: {test_dir}")
elif plugin_root.exists():
    test_dir = plugin_root
    print(f"[INFO] 使用项目源码目录: {test_dir}")
else:
    print(f"[ERROR] 找不到插件目录！")
    print(f"  已安装路径: {installed_plugin}")
    print(f"  项目路径: {plugin_root}")
    sys.exit(1)


print()
print("=" * 60)
print("QGIS Agent 安装诊断")
print("=" * 60)

# 步骤 1: 检查目录结构
print("\n[1/6] 检查插件目录结构...")
required_files = ["__init__.py", "plugin.py", "qgis_agent.py", "metadata.txt"]
required_dirs = ["agent", "icons"]

all_ok = True
for f in required_files:
    path = test_dir / f
    if path.exists():
        print(f"  OK {f} ({path.stat().st_size} bytes)")
    else:
        print(f"  MISSING {f}")
        all_ok = False

for d in required_dirs:
    path = test_dir / d
    if path.exists() and path.is_dir():
        count = len(list(path.glob("**/*.py")))
        print(f"  OK {d}/ ({count} Python files)")
    else:
        print(f"  MISSING {d}/")
        all_ok = False

if not all_ok:
    print("\n[ERROR] 插件文件不完整，请重新打包。")
    sys.exit(1)
else:
    print("  目录结构 OK 全部正常")

# 步骤 2: 测试 __init__.py 的 classFactory 加载逻辑
# 这模拟 QGIS 的加载过程
print("\n[2/6] 测试 classFactory 加载逻辑...")

# 手动模拟 QGIS 的加载环境
sys.path.insert(0, str(test_dir))

# 读取 __init__.py 内容
init_path = test_dir / "__init__.py"
init_content = init_path.read_text(encoding="utf-8")

# 打印关键行方便检查
print(f"  __init__.py 行数: {len(init_content.splitlines())}")

# 找到 classFactory 函数并打印其内容
for i, line in enumerate(init_content.splitlines(), 1):
    if "def classFactory" in line:
        print(f"  classFactory 定义在第 {i} 行:")
        for j in range(i-1, min(i+25, len(init_content.splitlines()))):
            print(f"    {j+1}: {init_content.splitlines()[j]}")
        break

# 手动执行 _load_qgis_agent_class 的逻辑来测试
print("\n[3/6] 模拟 QGIS 加载流程...")
sys.path.insert(0, str(test_dir))

# 方式 1: 通过 exec 模拟 QGIS 的导入
print("  执行 __init__.py 并调用 classFactory...")
try:
    # 创建一个模拟命名空间
    import types
    mock_module = types.ModuleType("qgis_agent")
    mock_module.__file__ = str(init_path)
    mock_module.__path__ = str(test_dir)

    # 在 mock_module 的命名空间中执行
    exec(compile(init_content, str(init_path), "exec"), mock_module.__dict__)

    print("  OK __init__.py 解析成功")

    # 检查 _load_qgis_agent_class 是否存在
    if hasattr(mock_module, "_load_qgis_agent_class"):
        print("  OK _load_qgis_agent_class 函数存在")
        # 测试它
        try:
            QgisAgent = mock_module._load_qgis_agent_class()
            print(f"  OK _load_qgis_agent_class() 返回: {QgisAgent}")
        except Exception as e:
            print(f"  FAIL _load_qgis_agent_class() 失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("  MISSING _load_qgis_agent_class")

    # 检查 classFactory
    if hasattr(mock_module, "classFactory"):
        print("  OK classFactory 函数存在")
    else:
        print("  MISSING classFactory")

except Exception as e:
    print(f"  FAIL __init__.py 执行失败: {e}")
    import traceback
    traceback.print_exc()

# 步骤 3: 测试各导入方式
print("\n[4/6] 测试各导入方式...")

# 先确保 sys.path 正确
sys.path.insert(0, str(test_dir))

# 测试 1: import plugin (绝对导入)
try:
    import plugin
    print("  OK from plugin import QgisAgent (绝对导入)")
except Exception as e:
    print(f"  FAIL 绝对导入 from plugin: {e}")

# 测试 2: import qgis_agent.plugin (如果父目录在 sys.path)
parent_dir = test_dir.parent
if str(parent_dir) in sys.path or parent_dir == Path.cwd():
    try:
        import qgis_agent.plugin
        print("  OK from qgis_agent.plugin import QgisAgent")
    except Exception as e:
        print(f"  FAIL 相对路径导入: {e}")
else:
    print("  SKIP qgis_agent.plugin (父目录不在 sys.path)")

# 步骤 4: 检查 LangChain 依赖
print("\n[5/6] 检查 LangChain 依赖...")
for pkg in ["langchain", "langchain_core", "langchain.agents", "litellm"]:
    try:
        __import__(pkg)
        print(f"  OK {pkg}")
    except ImportError:
        print(f"  MISSING {pkg} (QGIS 外部运行时正常)")

# 步骤 5: 检查 QGIS 依赖
print("\n[6/6] 检查 QGIS 依赖...")
try:
    from qgis.core import QgsProject
    from qgis.utils import iface
    print("  OK QGIS 模块可用")
except ImportError:
    print("  INFO QGIS 模块不可用（在 QGIS 外部运行时正常）")

# 总结
print()
print("=" * 60)
print("诊断完成")
print("=" * 60)
print(f"插件目录: {test_dir}")
print(f"Python: {sys.version}")
print(f"sys.path[0:4]: {sys.path[:4]}")

try:
    from qgis.utils import iface
    print("运行环境: QGIS 内部")
except ImportError:
    print("运行环境: QGIS 外部（命令行）")
