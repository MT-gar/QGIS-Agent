# -*- coding: utf-8 -*-
"""
表达式与字段计算工具

提供 QGIS 表达式引擎的操作能力：
- QgsExpression 计算
- 字段计算器操作
- 表达式语法验证
- 条件样式表达式
"""

from typing import Optional, List, Dict


def evaluate_expression(layer_id: str, expression: str, limit: int = 20) -> dict:
    """
    在图层中对每个要素执行表达式计算。

    :param layer_id: 图层 ID
    :param expression: QGIS 表达式（如 "$area", "$length", "\"name\" = '北京'"）
    :param limit: 最大返回条数
    :return: 计算结果列表
    """
    from qgis.core import (
        QgsProject, QgsExpression, QgsExpressionContext,
        QgsExpressionContextUtils,
    )

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 检查表达式语法
    expr = QgsExpression(expression)
    if expr.hasParserError():
        return {
            'error': f'表达式语法错误: {expr.parserErrorString()}',
            'expression': expression,
        }

    # 构建表达式上下文，使 $area、@变量、聚合等函数能拿到图层/要素上下文
    context = QgsExpressionContext()
    context.appendScopes(
        QgsExpressionContextUtils.globalProjectLayerScopes(layer)
    )

    # 执行计算
    results = []
    eval_error = None
    for i, feat in enumerate(layer.getFeatures()):
        if i >= limit:
            break
        context.setFeature(feat)
        value = expr.evaluate(context)
        # 求值后再检查 eval 错误（hasEvalError 必须在 evaluate 之后判断）
        if expr.hasEvalError():
            eval_error = expr.evalErrorString()
            break
        results.append({
            'feature_id': feat.id(),
            'expression': expression,
            'result': value,
            'attributes': dict(zip(
                [f.name() for f in layer.fields()],
                feat.attributes()
            )),
        })

    response = {
        'success': eval_error is None,
        'layer': layer_id,
        'expression': expression,
        'count': len(results),
        'results': results,
    }
    if eval_error:
        response['eval_error'] = eval_error
    return response


def calculate_field(layer_id: str, expression: str,
                    output_field_name: str, field_type: str = 'string',
                    field_length: int = 0) -> dict:
    """
    使用表达式为图层添加字段（字段计算器）。

    :param layer_id: 图层 ID
    :param expression: QGIS 表达式（如 "$area", "\"pop\" * 2"）
    :param output_field_name: 输出字段名称
    :param field_type: 输出字段类型 ('string', 'integer', 'double')
    :param field_length: 字段长度（字符串字段需要）
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsExpression

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 检查表达式语法
    expr = QgsExpression(expression)
    if expr.hasParserError():
        return {
            'error': f'表达式语法错误: {expr.parserErrorString()}',
            'expression': expression,
        }

    # native:fieldcalculator 的 FIELD_TYPE 取值：0=Decimal(double)、1=Integer、2=Text
    field_type_map = {'double': 0, 'float': 0, 'integer': 1, 'int': 1,
                      'string': 2, 'text': 2}
    qgis_field_type = field_type_map.get(field_type.lower(), 2)

    # 通过 Processing 的 fieldcalculator 算法执行（算法 ID 用冒号分隔）
    try:
        from qgis import processing

        params = {
            'INPUT': layer,
            'FIELD_NAME': output_field_name,
            'FIELD_TYPE': qgis_field_type,
            'FIELD_LENGTH': field_length,
            'FIELD_PRECISION': 10,
            'FORMULA': expression,
            'OUTPUT': 'memory:',
        }

        result = processing.run('native:fieldcalculator', params)

        # 把含新字段的结果图层加入项目，便于后续按 ID 访问
        out_layer = result.get('OUTPUT') if isinstance(result, dict) else None
        added_id = None
        if out_layer is not None and hasattr(out_layer, 'isValid') and out_layer.isValid():
            out_layer.setName(f'{layer.name()}_calc')
            project.addMapLayer(out_layer)
            added_id = out_layer.id()

        return {
            'success': True,
            'source_layer': layer_id,
            'new_field': output_field_name,
            'expression': expression,
            'output_layer_id': added_id,
            'note': '字段计算输出为新图层（已加入项目），原图层不变',
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'字段计算失败: {str(e)}',
            'hint': '建议使用 qgis_api_call 直接调用 QgsVectorLayer 编辑 API',
        }


def validate_expression(expression: str) -> dict:
    """
    验证 QGIS 表达式的语法正确性。

    :param expression: QGIS 表达式
    :return: 验证结果
    """
    from qgis.core import QgsExpression

    expr = QgsExpression(expression)

    return {
        'expression': expression,
        'is_valid': not expr.hasParserError(),
        'parser_error': expr.parserErrorString() if expr.hasParserError() else None,
        'has_eval_error': expr.hasEvalError(),
        'eval_error': expr.evalErrorString() if expr.hasEvalError() else None,
        'expected_type': str(expr.expectedType()) if hasattr(expr, 'expectedType') else 'unknown',
        'needs_geometry': expr.needsGeometry(),
    }


def list_available_functions() -> dict:
    """
    列出 QGIS 表达式引擎中可用的函数。

    :return: 函数分类列表
    """
    from qgis.core import QgsExpression

    # QGIS 表达式函数通过 QgsExpression.Function 注册
    # 这里返回常见的函数类别
    functions = {
        '数学': ['sum', 'avg', 'min', 'max', 'count', 'sqrt', 'sin', 'cos', 'tan', 'degrees', 'radians', 'pow', 'mod', 'floor', 'ceil', 'round', 'abs', 'exp', 'ln', 'log'],
        '字符串': ['concat', 'lower', 'upper', 'trim', 'ltrim', 'rtrim', 'left', 'right', 'mid', 'length', 'replace', 'substr', 'regexp_substr', 'regexp_replace', 'strpos', 'find', 'regexp_match'],
        '聚合': ['aggregate', 'array_agg', 'concatenate', 'count_distinct', 'sum_distinct', 'array_accumulate', 'array_any_true', 'array_every', 'array_filter', 'array_find', 'array_sort'],
        '日期/时间': ['now', 'current_date', 'current_time', 'date', 'time', 'year', 'month', 'day', 'hour', 'minute', 'second', 'make_date', 'make_time', 'make_datetime', 'date_add', 'date_diff', 'age'],
        '地理': ['area', 'length', 'distance', 'buffer', 'centroid', 'geometry_n', 'boundary', 'intersection', 'union', 'difference', 'within', 'contains', 'covers', 'intersects', 'equals', 'touches', 'overlaps', 'disjoint', 'relate', 'x', 'y', 'z', 'm', 'geom_to_wkt', 'geom_to_geojson', 'transform', 'project', 'point_n', 'start_point', 'end_point', 'n_points', 'nodes_to_array'],
        '条件': ['case', 'when', 'then', 'else', 'end', 'if', 'coalesce', 'nullif', 'isnull', 'isnotnull'],
        '数组': ['array', 'array_to_string', 'string_to_array', 'array_length', 'array_get', 'array_append', 'array_prepend', 'array_remove', 'array_join', 'array_sort', 'array_reverse', 'array_contains', 'array_foreach'],
        '变量': ['variable', 'user_full_name', 'user_name', 'project_name', 'project_path', 'project_folder', 'layer_name', 'layer_id', 'geometry_type'],
    }

    return functions


def field_statistics(layer_id: str, field_name: str) -> dict:
    """
    计算数值字段的基本统计信息。

    :param layer_id: 图层 ID
    :param field_name: 字段名称
    :return: 统计信息
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 查找字段索引
    field_index = layer.fields().indexOf(field_name)
    if field_index == -1:
        return {'error': f'字段不存在: {field_name}'}

    # 收集所有非空值
    values = []
    for feat in layer.getFeatures():
        val = feat.attributes()[field_index]
        if val is not None:
            try:
                values.append(float(val))
            except (ValueError, TypeError):
                continue

    if not values:
        return {'error': f'字段中没有可计算的数值'}

    values.sort()
    n = len(values)
    total = sum(values)
    mean = total / n
    min_val = values[0]
    max_val = values[-1]
    median = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2

    # 标准差
    if n > 1:
        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        stddev = variance ** 0.5
    else:
        stddev = 0

    return {
        'success': True,
        'layer': layer_id,
        'field': field_name,
        'count': n,
        'sum': total,
        'mean': mean,
        'median': median,
        'stddev': stddev,
        'min': min_val,
        'max': max_val,
        'range': max_val - min_val,
    }
