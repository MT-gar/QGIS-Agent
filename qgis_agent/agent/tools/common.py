# -*- coding: utf-8 -*-
"""
工具层公共辅助

提供各工具模块复用的图层查找等通用逻辑，统一返回结构，
减少各文件重复的图层存在性/类型校验样板代码。
"""

from typing import Optional, Tuple


def get_layer(layer_id: str):
    """
    按 ID 获取图层，统一处理"不存在"错误。

    :param layer_id: 图层 ID
    :return: (layer, error)。成功时 error 为 None；失败时 layer 为 None、
             error 为可直接返回给 LLM 的错误字典。
    """
    from qgis.core import QgsProject

    layers = QgsProject.instance().mapLayers()
    layer = layers.get(layer_id)
    if layer is None:
        return None, {'error': f'图层不存在: {layer_id}'}
    return layer, None


def is_raster(layer) -> bool:
    """判断图层是否为栅格图层（兼容不同 QGIS 版本的 type 表达）。"""
    try:
        from qgis.core import QgsMapLayerType
        return layer.type() == QgsMapLayerType.RasterLayer
    except Exception:
        # 回退：按类名判断
        return type(layer).__name__ == 'QgsRasterLayer'
