# -*- coding: utf-8 -*-
"""
图层/要素高级操作工具

提供对矢量图层的深度操作能力：
- 创建/删除图层
- 属性表操作：添加字段、计算字段、查询、排序
- 要素几何操作：修改几何、简化、重建
- 样式操作：分类渲染、颜色方案、标签
- 坐标系操作：获取 CRS、重投影、转换
"""

from typing import Any, Dict, List, Optional


def create_vector_layer(name: str, geometry_type: str, crs: Optional[str] = None,
                        fields: Optional[List[dict]] = None):
    """
    创建新的矢量图层。

    :param name: 图层名称
    :param geometry_type: 几何类型 ('point', 'line', 'polygon', 'multipoint', 'multilinestring', 'multipolygon')
    :param crs: CRS 代码（如 "EPSG:4326"），默认为 WGS 84
    :param fields: 字段定义列表，如 [{"name": "name", "type": "string", "length": 50}]
    :return: 图层信息
    """
    from qgis.core import (
        QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem
    )

    # 几何类型映射
    if _HAS_WKB_TYPES:
        geom_map = {
            'point': QgsWkbTypes.Point,
            'line': QgsWkbTypes.LineString,
            'polygon': QgsWkbTypes.Polygon,
            'multipoint': QgsWkbTypes.MultiPoint,
            'multilinestring': QgsWkbTypes.MultiLineString,
            'multipolygon': QgsWkbTypes.MultiPolygon,
        }
        wkb_type = geom_map.get(geometry_type.lower(), QgsWkbTypes.Point)
    else:
        # 降级：使用默认值
        wkb_type = 0  # Point 默认值

    # 构建 CRS
    crs_str = crs or 'EPSG:4326'

    # 构建字段定义。memory provider 的字段语法为 field=name:type，
    # 多字段需重复 &field=...（不能用逗号串联）
    field_clause = '&field=id:integer'
    if fields:
        parts = []
        for f in fields:
            fname = f.get('name')
            if not fname:
                continue
            ftype = f.get('type', 'string')
            parts.append(f'field={fname}:{ftype}')
        if parts:
            field_clause = '&' + '&'.join(parts)

    # 创建图层
    uri = f'{geometry_type}?crs={crs_str}{field_clause}'
    layer = QgsVectorLayer(uri, name, 'memory')

    if layer.isValid():
        QgsProject.instance().addMapLayer(layer)
        return {
            'success': True,
            'id': layer.id(),
            'name': layer.name(),
            'geometry_type': geometry_type,
            'crs': crs_str,
            'fields': [f.name() for f in layer.fields()],
        }
    else:
        return {'error': f'无法创建图层: {name}'}


def add_field(layer_id: str, field_name: str, field_type: str,
              field_length: Optional[int] = None):
    """
    向矢量图层添加字段。

    :param layer_id: 图层 ID
    :param field_name: 字段名称
    :param field_type: 字段类型 ('string', 'integer', 'double', 'boolean', 'date', 'datetime')
    :param field_length: 字段长度（字符串字段需要）
    :return: 操作结果
    """
    # QgsField 在 qgis.core，QVariant 在 qgis.PyQt.QtCore（不在 qgis.core）
    from qgis.core import QgsProject, QgsField
    from qgis.PyQt.QtCore import QVariant

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 类型映射
    type_map = {
        'string': QVariant.String,
        'text': QVariant.String,
        'integer': QVariant.Int,
        'int': QVariant.Int,
        'double': QVariant.Double,
        'float': QVariant.Double,
        'boolean': QVariant.Bool,
        'bool': QVariant.Bool,
        'date': QVariant.Date,
        'datetime': QVariant.DateTime,
    }

    qvariant_type = type_map.get(field_type.lower(), QVariant.String)

    # 检查字段是否已存在
    field_names = [f.name() for f in layer.fields()]
    if field_name in field_names:
        return {'error': f'字段已存在: {field_name}'}

    field = QgsField(field_name, qvariant_type, '', field_length or 0)

    # 若图层已处于编辑会话，仅追加字段，提交交由 stop_editing 统一处理，
    # 避免连带提交会话中其他未保存的修改；否则自行开启编辑并提交
    already_editing = layer.isEditable()
    if not already_editing and not layer.startEditing():
        return {'error': '无法进入编辑模式'}

    if not layer.addAttribute(field):
        if not already_editing:
            layer.rollBack()
        return {'error': f'添加字段失败: {field_name}'}

    if already_editing:
        return {'success': True, 'field': field_name,
                'note': '字段已加入编辑缓冲，请用 stop_editing 提交'}

    if not layer.commitChanges():
        errors = '; '.join(layer.commitErrors())
        layer.rollBack()
        return {'error': f'提交字段失败: {errors}'}
    return {'success': True, 'field': field_name}


def query_features(layer_id: str, filter_expression: Optional[str] = None,
                   limit: Optional[int] = 100) -> dict:
    """
    查询矢量图层中的要素。

    :param layer_id: 图层 ID
    :param filter_expression: SQL 过滤表达式（可选）
    :param limit: 返回的最大要素数
    :return: 查询结果
    """
    from qgis.core import QgsProject, QgsExpression, QgsFeatureRequest

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 构建过滤条件
    if filter_expression:
        expr = QgsExpression(filter_expression)
        if expr.hasParserError():
            return {'error': f'表达式语法错误: {expr.parserErrorString()}'}
        filter_req = QgsFeatureRequest(expr)
    else:
        filter_req = QgsFeatureRequest()

    # limit 显式为 None 时不设限制，避免 setLimit(None) 抛错
    if limit is not None:
        filter_req.setLimit(limit)

    # 获取要素
    features = list(layer.getFeatures(filter_req))
    results = []

    for feat in features:
        row = {
            'id': feat.id(),
            'attributes': dict(zip(
                [f.name() for f in layer.fields()],
                feat.attributes()
            )),
        }
        geom = feat.geometry()
        if geom and not geom.isNull():
            geom_type = geom.typeName()
            if geom_type == 'Point':
                coords = geom.asPoint()
                row['geometry_summary'] = f'POINT({coords.x():.6f} {coords.y():.6f})'
            elif geom_type == 'MultiPoint':
                row['geometry_summary'] = f'MULTIPOINT ({len(geom.asMultiPoint())} 个点)'
            elif geom_type == 'LineString':
                coords = geom.asPolyline()
                row['geometry_summary'] = f'LINESTRING ({len(coords)} 个点)'
            elif geom_type == 'MultiLineString':
                row['geometry_summary'] = f'MULTILINESTRING ({len(geom.asMultiPolyline())} 条线)'
            elif geom_type == 'Polygon':
                rings = geom.asPolygon()
                if rings:
                    row['geometry_summary'] = f'POLYGON ({len(rings)} 个环)'
                else:
                    row['geometry_summary'] = 'POLYGON'
            elif geom_type == 'MultiPolygon':
                row['geometry_summary'] = f'MULTIPOLYGON ({len(geom.asMultiPolygon())} 个面)'
            else:
                row['geometry_summary'] = f'{geom_type}'

        results.append(row)

    return {
        'success': True,
        'layer': layer_id,
        'count': len(results),
        'features': results,
    }


def select_features(layer_id: str, filter_expression: str) -> dict:
    """
    选择图层中符合条件的要素。

    :param layer_id: 图层 ID
    :param filter_expression: 过滤表达式
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsExpression

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    expression = QgsExpression(filter_expression)

    if expression.hasParserError():
        return {'error': f'表达式语法错误: {expression.parserErrorString()}'}

    # 选择要素
    layer.selectByExpression(filter_expression)
    selected_count = layer.selectedFeatureCount()

    return {
        'success': True,
        'layer': layer_id,
        'selected': selected_count,
    }


def get_layer_crs(layer_id: str) -> str:
    """
    获取图层的 CRS。

    :param layer_id: 图层 ID
    :return: CRS 代码（如 "EPSG:4326"）
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return f'图层不存在: {layer_id}'

    layer = layers[layer_id]
    crs = layer.crs()
    return crs.authid() if crs.isValid() else '未设置 CRS'


def reproject_layer(layer_id: str, dest_crs: str,
                    output_path: Optional[str] = None) -> dict:
    """
    重投影图层到目标 CRS。

    使用 Processing 算法 native_reprojectlayer 执行实际重投影。
    如果不指定 output_path，结果将作为临时图层加载到项目中。

    :param layer_id: 图层 ID
    :param dest_crs: 目标 CRS 代码（如 "EPSG:3857"）
    :param output_path: 输出文件路径（可选，默认输出到内存）
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsCoordinateReferenceSystem

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    src_crs = layer.crs()

    # 校验目标 CRS：支持 "EPSG:3857"、"3857"、"ESRI:102100" 等多种写法
    target_str = dest_crs if ':' in dest_crs else f'EPSG:{dest_crs}'
    target_crs = QgsCoordinateReferenceSystem(target_str)
    if not target_crs.isValid():
        return {'error': f'无效的 CRS 代码: {dest_crs}'}

    # 确定输出路径（不指定则输出到内存）
    output = output_path or 'memory:'

    # 使用 Processing 执行实际重投影
    params = {
        'INPUT': layer,
        'TARGET_CRS': target_crs,
        'OUTPUT': output,
    }

    try:
        from qgis import processing
        result = processing.run('native:reprojectlayer', params)

        # 未指定输出路径时，把内存结果图层加入项目，便于后续 list_layers 找到
        out_layer = result.get('OUTPUT') if isinstance(result, dict) else None
        added_id = None
        if not output_path and out_layer is not None and hasattr(out_layer, 'isValid'):
            if out_layer.isValid():
                project.addMapLayer(out_layer)
                added_id = out_layer.id()

        return {
            'success': True,
            'layer': layer_id,
            'src_crs': src_crs.authid(),
            'dest_crs': target_crs.authid() or target_str,
            'output_layer_id': added_id,
            'message': f'图层 {layer_id} 已重投影到 {target_str}',
        }
    except Exception as e:
        return {'error': f'重投影失败: {str(e)}'}


def save_layer_as(layer_id: str, output_path: str, driver_name: str = 'GeoJSON') -> dict:
    """
    将图层导出为不同格式。

    :param layer_id: 图层 ID
    :param output_path: 输出文件路径
    :param driver_name: 输出驱动名称（'GeoJSON', 'GPKG', 'CSV', 'ESRI Shapefile'）
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsVectorFileWriter, QgsCoordinateTransformContext

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    # 使用 QGIS 3.20+/4.x 推荐的 writeAsVectorFormatV3 API
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver_name

    try:
        transform_context = project.transformContext()
    except Exception:
        transform_context = QgsCoordinateTransformContext()

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer, output_path, transform_context, options
    )

    # 返回值为元组，首元素为错误码（NoError 表示成功）
    error_code = result[0] if isinstance(result, (tuple, list)) else result
    if error_code == QgsVectorFileWriter.NoError:
        return {'success': True, 'path': output_path, 'format': driver_name}
    else:
        msg = result[1] if isinstance(result, (tuple, list)) and len(result) > 1 else str(error_code)
        return {'error': f'导出失败: {msg}'}

# === QGIS 4.0 兼容类型 ===

# QgsWkbTypes 在 qgis.core
try:
    from qgis.core import QgsWkbTypes
    _HAS_WKB_TYPES = True
except ImportError:
    _HAS_WKB_TYPES = False

try:
    from qgis.core import QgsFeatureRequest
except ImportError:
    QgsFeatureRequest = None

# QgsField 在 qgis.core；QVariant 在 qgis.PyQt.QtCore（不在 qgis.core）
try:
    from qgis.core import QgsField
except ImportError:
    QgsField = None
try:
    from qgis.PyQt.QtCore import QVariant
except ImportError:
    QVariant = None
