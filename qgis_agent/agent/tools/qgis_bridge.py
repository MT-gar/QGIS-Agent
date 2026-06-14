# -*- coding: utf-8 -*-
"""
QGIS API 通用桥接工具

这是整个插件的核心工具。它暴露 QGIS 全部 API 给 AI Agent，
使 Agent 可以通过自然语言描述调用任何 QGIS 功能。

设计思路：
1. 自动发现 qgis.core 和 qgis.gui 中的所有公开类
2. 建立类名到模块路径的映射
3. 将 iface 实例及其方法暴露给 Agent
4. 支持链式调用（如 iface.mapCanvas().extent().toString()）
5. **关键修复**: 参数通过 **kwargs 直接传入结构化值，不再需要双重序列化

Agent 通过此工具可以调用：
- qgis.core 中的 1467+ 个类
- qgis.gui 中的 734+ 个类
- iface (QgisInterface) 中的 329 个方法
"""

import re
import os
import sys
from typing import Any, Optional


class QGisAPIBridge:
    """
    QGIS API 通用桥接器。

    将 qgis.core、qgis.gui 和 iface 的所有公开类和方法
    暴露为 Agent 可调用的统一接口。

    修复后的使用方式：
    - bridge.call("iface.addVectorLayer", path="data.shp", name="test", provider="ogr")
      → **kwargs 直接传入结构化参数（推荐）
    - bridge.call("QgsProject.instance().mapLayers()")
      → 纯路径，无需参数（简单场景）
    - bridge.call("iface.mapCanvas().extent().toString()")
      → 纯路径，获取返回值

    核心变化：
    - 路径中的括号参数作为 fallback（兼容旧格式）
    - **kwargs 是主要传参方式（由 LangChain StructuredTool 传入结构化值）
    - 移除了 ast.literal_eval 双重序列化
    """

    def __init__(self, iface=None):
        """
        初始化桥接器。

        :param iface: QGIS 接口对象 (QgisInterface)。
                      如果是 None，则在首次调用时延迟获取。
        """
        self._iface = iface
        self._core_classes = {}   # 类名 -> 类对象的映射
        self._gui_classes = {}    # 类名 -> 类对象的映射
        self._iface_methods = {}  # iface 方法名 -> 方法引用
        self._discovered = False  # 是否已发现类

    @property
    def iface(self):
        """
        获取 QGIS 接口对象（懒加载）。

        在插件上下文中，从 qgis.utils 导入 iface。
        在测试或 standalone 模式下，可手动设置。

        :return: QgisInterface 实例
        """
        if self._iface is not None:
            return self._iface
        try:
            from qgis.utils import iface
            self._iface = iface
            return iface
        except ImportError:
            return None

    def _discover_classes(self):
        """
        自动发现 qgis.core 和 qgis.gui 中的所有公开类。

        扫描模块中所有以大写字母开头的公开符号，
        过滤出类和枚举类型，建立类名到对象的映射。
        """
        if self._discovered:
            return

        # 注册 qgis 路径
        import qgis
        qgis_path = os.path.dirname(qgis.__file__)
        if qgis_path not in sys.path:
            sys.path.insert(0, qgis_path)

        # 发现 qgis.core 类
        try:
            import qgis.core as qc
            self._core_classes = self._scan_module(qc, 'core')
        except Exception as e:
            print(f'[QgisBridge] 发现 qgis.core 类时出错: {e}')

        # 发现 qgis.gui 类
        try:
            import qgis.gui as qg
            self._gui_classes = self._scan_module(qg, 'gui')
        except Exception as e:
            print(f'[QgisBridge] 发现 qgis.gui 类时出错: {e}')

        # 发现 iface 方法
        if self.iface is not None:
            self._iface_methods = {
                name: getattr(self.iface, name)
                for name in dir(self.iface)
                if not name.startswith('_') and callable(getattr(self.iface, name))
            }

        self._discovered = True

    def _scan_module(self, module, module_name):
        """
        扫描模块中的所有公开类和枚举。

        :param module: 要扫描的 Python 模块（如 qgis.core）
        :param module_name: 模块名称（core/gui），用于错误日志
        :return: 类名到类对象的映射字典
        """
        classes = {}
        for name in dir(module):
            if name.startswith('_'):
                continue
            obj = getattr(module, name)
            # 检查是否为类或枚举
            if isinstance(obj, type):
                classes[name] = obj
        return classes

    def _resolve_class(self, class_name):
        """
        通过类名解析为实际的 Python 类对象。

        优先从 qgis.core 中查找，然后从 qgis.gui 中查找。

        :param class_name: 类名（如 QgsVectorLayer）
        :return: 类对象或 None
        """
        if class_name in self._core_classes:
            return self._core_classes[class_name]
        if class_name in self._gui_classes:
            return self._gui_classes[class_name]
        return None

    # ---------------------------------------------------------------
    # 参数解析（仅处理路径括号内的简单参数）
    # ---------------------------------------------------------------

    def _parse_method_params(self, params_str):
        """
        解析方法路径括号内的简单参数（fallback 方式）。

        用于兼容旧格式：bridge.call("iface.addVectorLayer(path='data.shp', name='test')")
        主要传参方式是通过 **kwargs（推荐）。

        修复：不再使用 ast.literal_eval 包裹，而是智能分割引号内的逗号。

        :param params_str: 参数字符串
        :return: 参数字典
        """
        if not params_str or not params_str.strip():
            return {}

        result = {}
        # 智能分割参数，正确处理引号内的逗号
        pairs = self._split_params(params_str)
        for pair in pairs:
            pair = pair.strip()
            if '=' in pair:
                key, value = pair.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                result[key] = self._try_convert(value)
        return result

    def _split_params(self, params_str):
        """
        智能分割参数，正确处理引号内的逗号。

        例如: "path='C:/data/file.shp', name='test'"
             → ['path=C:/data/file.shp', 'name=test']

        :param params_str: 参数字符串
        :return: 参数字符串列表
        """
        parts = []
        current = ''
        in_quote = False
        quote_char = None

        for ch in params_str:
            if ch in ('"', "'") and not in_quote:
                in_quote = True
                quote_char = ch
                current += ch
            elif ch == quote_char and in_quote:
                in_quote = False
                quote_char = None
                current += ch
            elif ch == ',' and not in_quote:
                parts.append(current)
                current = ''
            else:
                current += ch

        if current.strip():
            parts.append(current)

        return parts

    def _try_convert(self, value_str):
        """
        尝试将字符串转换为适当的 Python 类型。

        :param value_str: 值字符串
        :return: 转换后的值
        """
        if value_str.lower() == 'true':
            return True
        if value_str.lower() == 'false':
            return False
        if value_str.lower() == 'none' or value_str == '':
            return None
        try:
            return int(value_str)
        except ValueError:
            pass
        try:
            return float(value_str)
        except ValueError:
            pass
        return value_str

    # ---------------------------------------------------------------
    # 核心方法
    # ---------------------------------------------------------------

    def call(self, method_path: str, **kwargs):
        """
        通过方法路径字符串调用 QGIS API。

        这是最核心的方法。Agent 通过自然语言描述需求，
        此方法解析路径并执行调用。

        修复后推荐使用方式（**kwargs 传入结构化值）：
            bridge.call("iface.addVectorLayer",
                        path="/data/points.shp",
                        name="点图层",
                        provider="ogr")
            bridge.call("QgsProject.instance().mapLayers()")

        也兼容旧格式（路径内嵌参数，作为 fallback）：
            bridge.call("iface.addVectorLayer(path='/data.shp', name='test', provider='ogr')")

        :param method_path: 方法路径字符串（如 "iface.addVectorLayer"）
        :param kwargs: 关键字参数（由 LangChain StructuredTool 自动传入结构化值）
        :return: 调用结果
        """
        self._discover_classes()

        try:
            # 剥离路径中的括号和参数（用于兼容旧格式）
            match = re.match(r'^([^(]+)\((.*)\)$', method_path.strip(), re.DOTALL)
            if match:
                full_path = match.group(1).strip()
                fallback_params_str = match.group(2)
            else:
                full_path = method_path.strip()
                fallback_params_str = ''

            # 按 '.' 分割路径段
            parts = full_path.split('.')

            # 解析起始对象
            if parts[0] == 'iface':
                current_obj = self.iface
            else:
                current_obj = self._resolve_class(parts[0])

            if current_obj is None:
                return {'error': f'无法解析对象: {parts[0]}'}

            # 解析路径括号内的 fallback 参数
            fallback_params = self._parse_method_params(fallback_params_str)

            # 逐段链式调用
            # 对于每个后续段，检查是否有括号（即是否是方法调用）
            for i in range(1, len(parts)):
                segment = parts[i].strip()
                is_last = (i == len(parts) - 1)

                # 检查是否带括号（方法调用）
                seg_match = re.match(r'^(\w+)\((.*)\)$', segment, re.DOTALL)
                if seg_match:
                    method_name = seg_match.group(1)
                    seg_params_str = seg_match.group(2)

                    # 获取方法
                    method = getattr(current_obj, method_name, None)
                    if method is None:
                        return {'error': f'方法不存在: {method_path}'}

                    # 合并参数：路径括号内参数为 fallback；
                    # **kwargs 只应作用于"最后一段"方法，避免被注入到中间段
                    # （如 instance() ）导致 TypeError
                    if seg_params_str:
                        all_params = dict(self._parse_method_params(seg_params_str))
                    else:
                        all_params = {}
                    if is_last:
                        all_params = {**fallback_params, **all_params, **kwargs}

                    # 特殊处理：将字符串图层引用转换为 QgsMapLayer 对象
                    all_params = self._resolve_layer_refs(all_params)

                    # 执行调用
                    result = method(**all_params)

                    # 如果不是最后一层，继续链式调用
                    if not is_last:
                        current_obj = result
                    else:
                        # 最后一层，处理结果
                        return self._format_result(result, method_path)
                else:
                    # 不带括号的属性访问
                    attr = getattr(current_obj, segment, None)
                    if attr is None:
                        return {'error': f'属性不存在: {segment}'}
                    current_obj = attr

            # 没有到达任何方法调用，返回对象引用
            return {'result': str(current_obj), '_type': type(current_obj).__name__}

        except Exception as e:
            return {'error': f'调用失败: {str(e)}', 'method': method_path}

    def _format_result(self, result, method_path):
        """
        智能格式化调用结果。

        :param result: 方法调用结果
        :param method_path: 原始方法路径（用于错误报告）
        :return: 格式化后的结果字典
        """
        result_type = type(result).__name__

        # 特定的 QGIS 对象格式化
        if hasattr(result, 'toString'):
            return {'result': result.toString(), '_type': result_type}
        elif hasattr(result, 'asDictionary'):
            return {'result': result.asDictionary(), '_type': result_type}
        elif hasattr(result, 'asWkt'):
            return {'result': result.asWkt(), '_type': result_type}
        elif hasattr(result, '__iter__') and not isinstance(result, (str, dict)):
            # 可迭代对象（如图层字典）
            # 注意：排除 QgsRectangle、QgsPoint 等 QGIS 对象
            try:
                items = list(result)
                # 如果遍历结果是 (key, value) 元组（如 dict.items()）
                return {
                    'result': {str(k): str(v) for k, v in items[:20]},
                    '_count': len(items),
                    '_type': result_type,
                }
            except (TypeError, ValueError, StopIteration):
                # 非键值对的可迭代（如要素列表）：退化为元素字符串列表
                try:
                    return {
                        'result': [str(x) for x in list(result)[:20]],
                        '_type': result_type,
                    }
                except Exception:
                    return {'result': str(result), '_type': result_type}
        # 其余类型统一字符串化（确保任何分支都有返回值，不会落空返回 None）
        return {'result': str(result) if result is not None else None, '_type': result_type}

    def _resolve_layer_refs(self, params, known_input_keys=None):
        """
        将字符串图层引用解析为 QgsMapLayer 对象。

        修复：只替换已知输入参数名中的值，不再盲目替换所有字符串。
        避免路径字符串（如 "roads.shp"）被错误替换为图层对象。

        :param params: 参数字典
        :param known_input_keys: 已知的输入参数名集合（默认使用 Processing 标准名）
        :return: 处理后的参数字典
        """
        if not params:
            return params

        # 仅替换"明确是图层输入"的参数名，避免把字段名(FIELD)、输出路径(OUTPUT)、
        # CRS/EXTENT 等与图层重名却语义不同的值误换为图层对象
        known = known_input_keys or {
            'INPUT', 'INPUT_LAYER', 'LAYER', 'SOURCE',
            'OVERLAY', 'RASTER', 'VECTOR', 'INPUT_RASTER',
        }

        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            layers = project.mapLayers()

            # 构建名称映射
            layer_by_name = {v.name(): v for v in layers.values()}

            # 返回新字典，不原地修改调用方传入的 dict（避免副作用外泄）
            resolved = dict(params)
            for key, value in params.items():
                if not isinstance(value, str):
                    continue
                if key.upper() not in known:
                    continue
                if value in layers:
                    resolved[key] = layers[value]
                elif value in layer_by_name:
                    resolved[key] = layer_by_name[value]
            return resolved
        except Exception:
            return params

    def list_classes(self, module='all'):
        """
        列出所有已发现的 QGIS 类。

        :param module: 'core' / 'gui' / 'all'
        :return: 类名字典
        """
        self._discover_classes()

        if module == 'core':
            return dict(self._core_classes)
        elif module == 'gui':
            return dict(self._gui_classes)
        else:
            return {
                'core': dict(self._core_classes),
                'gui': dict(self._gui_classes),
                'iface_methods': list(self._iface_methods.keys())
            }

    def get_class_doc(self, class_name):
        """
        获取类的文档字符串。

        :param class_name: 类名
        :return: 类的文档字符串
        """
        self._discover_classes()

        cls = self._resolve_class(class_name)
        if cls is None:
            return f'未知类: {class_name}'

        doc = cls.__doc__ or ''
        methods = [m for m in dir(cls) if not m.startswith('_') and callable(getattr(cls, m, None))]
        return f'{doc}\n\n可用方法: {", ".join(methods[:30])}'

    def get_interface_methods(self):
        """
        列出 iface 的所有方法。

        :return: iface 方法名列表
        """
        self._discover_classes()
        return list(self._iface_methods.keys())


# 模块级全局实例（在插件加载后初始化）
_global_bridge = None


def get_bridge(iface=None):
    """
    获取全局 QGIS API 桥接器实例。

    :param iface: QGIS 接口对象（可选，在插件中自动获取）
    :return: QGisAPIBridge 实例
    """
    global _global_bridge
    if _global_bridge is None:
        _global_bridge = QGisAPIBridge(iface=iface)
    return _global_bridge


def reset_bridge():
    """重置全局桥接器（用于测试）。"""
    global _global_bridge
    _global_bridge = None
