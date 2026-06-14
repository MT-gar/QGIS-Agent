# -*- coding: utf-8 -*-
"""
编辑操作工具

提供对矢量图层的编辑能力：
- 开始/停止编辑
- 添加/修改/删除要素
- 属性编辑
- 撤销/重做
"""

from typing import Any, Dict, List, Optional


def start_editing(layer_id: str) -> dict:
    """
    开始对图层进行编辑。

    :param layer_id: 图层 ID
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    if layer.isEditable():
        return {'success': True, 'message': '图层已在编辑模式'}

    if layer.startEditing():
        return {'success': True, 'message': '已开始编辑图层'}
    else:
        return {'error': '无法开始编辑'}


def stop_editing(layer_id: str, save: bool = True) -> dict:
    """
    停止编辑图层。

    :param layer_id: 图层 ID
    :param save: 是否保存更改
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    if not layer.isEditable():
        return {'success': True, 'message': '图层不在编辑模式'}

    if save:
        if layer.commitChanges():
            return {'success': True, 'message': '已保存并停止编辑'}
        # 提交失败：报告 commitErrors，图层仍处于编辑状态
        errors = '; '.join(layer.commitErrors())
        return {'error': f'提交失败，更改未保存: {errors}'}
    else:
        layer.rollBack()
        return {'success': True, 'message': '已放弃更改并停止编辑'}


def add_feature(layer_id: str, attributes: Optional[dict] = None,
                geometry_wkt: Optional[str] = None) -> dict:
    """
    向矢量图层添加要素。

    :param layer_id: 图层 ID
    :param attributes: 属性字典，键为字段名，值为属性值
    :param geometry_wkt: 几何 WKT 字符串（如 'POINT(116.4 39.9)'），可选
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsFeature, QgsGeometry

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    if not layer.isEditable():
        return {'error': '图层不在编辑模式，请先调用 start_editing'}

    # 创建要素
    feat = QgsFeature(layer.fields())

    # 设置属性（不匹配的字段名仅记录警告，不中断添加流程）
    warning = None
    if attributes:
        field_names = [f.name() for f in layer.fields()]
        matched = set()
        for key, value in attributes.items():
            if key in field_names:
                feat[key] = value
                matched.add(key)
        unmatched = set(attributes.keys()) - matched
        if unmatched:
            warning = f'以下字段名在图层中不存在，已忽略: {", ".join(sorted(unmatched))}'

    # 设置几何（无效 WKT 不静默丢弃，明确报错）
    if geometry_wkt:
        geom = QgsGeometry.fromWkt(geometry_wkt)
        if geom is None or geom.isNull():
            return {'error': f'无效的几何 WKT: {geometry_wkt}'}
        feat.setGeometry(geom)

    # 添加要素，检查返回值（addFeature 返回 False 表示失败）
    result = layer.addFeature(feat)
    if not result:
        return {'error': '添加要素失败（addFeature 返回 False）'}

    response = {'success': True, 'feature_added': True}
    if warning:
        response['warning'] = warning
    return response


def delete_feature(layer_id: str, feature_id: int) -> dict:
    """
    删除图层中的指定要素。

    :param layer_id: 图层 ID
    :param feature_id: 要素 ID
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    if not layer.isEditable():
        return {'error': '图层不在编辑模式'}

    if layer.deleteFeature(feature_id):
        return {'success': True, 'deleted': feature_id}
    return {'error': '删除失败'}


def delete_selected_features(layer_id: str) -> dict:
    """
    删除图层中所有已选择的要素。

    :param layer_id: 图层 ID
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]

    if not layer.isEditable():
        return {'error': '图层不在编辑模式'}

    count = layer.selectedFeatureCount()
    if count == 0:
        return {'success': True, 'deleted': 0, 'message': '没有已选择的要素'}

    # 逐个删除，统计实际成功数（不在此提交，提交统一交给 stop_editing，
    # 避免连带提交编辑会话中其他未保存的修改）
    deleted = 0
    for feat_id in layer.selectedFeatureIds():
        if layer.deleteFeature(feat_id):
            deleted += 1

    result = {'success': True, 'deleted': deleted}
    if deleted != count:
        result['warning'] = f'选中 {count} 个，实际删除 {deleted} 个'
    result['note'] = '删除已写入编辑缓冲，请用 stop_editing 提交以持久化'
    return result


def edit_attribute(layer_id: str, feature_id: int, field_name: str,
                   value: Any) -> dict:
    """
    修改要素的属性值。

    :param layer_id: 图层 ID
    :param feature_id: 要素 ID
    :param field_name: 字段名称
    :param value: 新属性值
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    field_index = layer.fields().indexOf(field_name)

    if field_index == -1:
        return {'error': f'字段不存在: {field_name}'}

    if not layer.isEditable():
        return {'error': '图层不在编辑模式'}

    if layer.changeAttributeValue(feature_id, field_index, value):
        return {'success': True, 'feature': feature_id, 'field': field_name, 'value': value}
    return {'error': '修改失败'}


def get_selected_features(layer_id: str, limit: int = 20) -> dict:
    """
    获取图层中已选择的要素信息。

    :param layer_id: 图层 ID
    :param limit: 最大返回数量
    :return: 选中要素信息
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    selected = list(layer.selectedFeatures())[:limit]

    results = []
    for feat in selected:
        results.append({
            'id': feat.id(),
            'attributes': dict(zip(
                [f.name() for f in layer.fields()],
                feat.attributes()
            )),
        })

    return {
        'success': True,
        'layer': layer_id,
        'selected_count': layer.selectedFeatureCount(),
        'features': results,
    }


def clear_selection(layer_id: str) -> dict:
    """
    清除图层中的选择。

    :param layer_id: 图层 ID
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layers[layer_id].setSelection([])
    return {'success': True}
