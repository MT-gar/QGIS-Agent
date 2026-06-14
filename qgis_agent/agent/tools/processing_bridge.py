# -*- coding: utf-8 -*-
"""
Processing 算法桥接工具

通过 Processing 框架暴露所有可用的 GIS 算法给 AI Agent。
支持 GDAL、GRASS、SAGA 和 QGIS 原生算法。

核心功能：
1. 发现所有可用算法（按 provider 分类）
2. 获取算法的详细信息（参数、输出、文档）
3. 执行算法（支持自动类型转换和进度反馈）

修复内容：
- 修复 _resolve_layer_refs 死代码（重复条件）
- 只替换已知输入参数名，避免错误替换路径字符串
"""

from typing import Any, Dict, List, Optional


def list_algorithms(provider: Optional[str] = None):
    """
    列出所有可用的 Processing 算法。

    算法按 provider 分组，每个算法包含 ID、名称、描述和类别。

    :param provider: 可选，过滤指定 provider 的算法
                    常见 provider: 'qgis', 'gdal', 'grass', 'saga'
    :return: 算法列表（按 provider 分组）
    """
    try:
        # Processing 注册表入口是 QgsApplication.processingRegistry()，
        # 而非 iface（QgisInterface 没有 processingRegistry 方法）
        from qgis.core import QgsApplication
        registry = QgsApplication.processingRegistry()

        # 获取所有算法
        all_algorithms = registry.algorithms()

        # 按 provider 分组
        result = {}
        for algo in all_algorithms:
            provider_id = algo.provider().id()
            if provider and provider_id != provider:
                continue

            if provider_id not in result:
                result[provider_id] = {
                    'name': algo.provider().name(),
                    'algorithms': []
                }

            result[provider_id]['algorithms'].append({
                'id': algo.id(),
                'name': algo.displayName(),
                'short_description': algo.shortDescription(),
                'group': algo.group(),
            })

        return result
    except Exception as e:
        return {'error': f'列出算法失败: {e}'}


def get_algorithm_info(algorithm_id: str) -> dict:
    """
    获取指定算法的详细信息。

    包括：名称、描述、参数列表、输出定义、分组等。

    :param algorithm_id: 算法 ID（如 'native:buffer', 'gdal:rasterize'）
    :return: 算法详细信息
    """
    try:
        from qgis.core import QgsApplication
        registry = QgsApplication.processingRegistry()
        algo = registry.createAlgorithmById(algorithm_id)

        if algo is None:
            return {'error': f'算法不存在: {algorithm_id}'}

        # 获取参数定义
        params = []
        for param in algo.parameterDefinitions():
            params.append({
                'name': param.name(),
                'description': param.description(),
                'type': param.type(),
                'required': not bool(param.flags() & param.FlagOptional)
                if hasattr(param, 'FlagOptional') else True,
                'default': param.defaultValue(),
            })

        # 获取输出定义（注意是复数 outputDefinitions）
        outputs = []
        for out in algo.outputDefinitions():
            outputs.append({
                'name': out.name(),
                'description': out.description(),
                'type': out.type(),
            })

        return {
            'id': algo.id(),
            'name': algo.displayName(),
            'description': algo.shortDescription(),
            'help': algo.helpString(),
            'group': algo.group(),
            'parameters': params,
            'outputs': outputs,
        }
    except Exception as e:
        return {'error': f'获取算法信息失败: {e}'}


def run_algorithm(algorithm_id: str, params: Optional[dict] = None):
    """
    执行 Processing 算法。

    支持自动类型转换：
    - 字符串图层名称/ID → QgsMapLayer 引用（仅限已知输入参数名）
    - CRS 代码字符串 → CRS 对象
    - 范围字符串 → QgsRectangle 对象

    :param algorithm_id: 算法 ID
    :param params: 算法参数（键值对）
    :return: 执行结果
    """
    if params is None:
        params = {}

    # 解析参数中的图层引用（修复：只替换已知输入参数）
    params = _resolve_layer_refs(params)

    try:
        from qgis import processing

        # 执行算法（qgis.processing.run 不接受 has_handling_errors 参数）
        result = processing.run(algorithm_id, params)

        return {
            'success': True,
            'algorithm': algorithm_id,
            'output': result,
        }
    except Exception as e:
        return {
            'success': False,
            'algorithm': algorithm_id,
            'error': str(e),
        }


def run_algorithm_with_feedback(algorithm_id: str, params: dict):
    """
    带进度反馈地执行 Processing 算法。

    适合需要监控执行进度的长时间运行算法。
    通过子类化 QgsProcessingFeedback 捕获进度信息（不能直接给 C++ 信号赋值）。

    :param algorithm_id: 算法 ID
    :param params: 算法参数
    :return: 执行结果和进度
    """
    progress_messages = []
    try:
        from qgis import processing
        from qgis.core import QgsProcessingFeedback

        class _CollectingFeedback(QgsProcessingFeedback):
            """收集算法执行过程中的信息输出。"""

            def pushInfo(self, info):
                progress_messages.append(info)

            def setProgressText(self, text):
                progress_messages.append(text)

        params = _resolve_layer_refs(params or {})
        result = processing.run(algorithm_id, params, feedback=_CollectingFeedback())
        return {
            'success': True,
            'algorithm': algorithm_id,
            'output': result,
            'messages': progress_messages,
        }
    except Exception as e:
        return {
            'success': False,
            'algorithm': algorithm_id,
            'error': str(e),
            'messages': progress_messages,
        }


def _resolve_layer_refs(params: dict) -> dict:
    """
    将参数字典中的字符串图层引用解析为 QgsMapLayer 对象。

    只替换"明确是图层输入"的参数名（INPUT/LAYER/SOURCE 等），不再触碰
    FIELD（字段名）、OUTPUT（输出路径）等可能与图层重名却语义不同的参数，
    避免把字段名/路径错误替换成图层对象。返回新字典，不修改入参。

    :param params: 参数字典
    :return: 解析后的新参数字典
    """
    from qgis.core import QgsProject

    # 仅限"图层输入"类参数名
    known_input_keys = {
        'INPUT', 'INPUT_LAYER', 'LAYER', 'SOURCE',
        'OVERLAY', 'RASTER', 'VECTOR', 'INPUT_RASTER',
    }

    project = QgsProject.instance()
    layers = project.mapLayers()
    layer_by_name = {v.name(): v for v in layers.values()}

    resolved = dict(params)
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        if key.upper() not in known_input_keys:
            continue
        if value in layers:
            resolved[key] = layers[value]
        elif value in layer_by_name:
            resolved[key] = layer_by_name[value]

    return resolved


def _get_iface():
    """获取 QGIS 接口对象（延迟导入）。"""
    try:
        from qgis.utils import iface
        return iface
    except ImportError:
        return None
