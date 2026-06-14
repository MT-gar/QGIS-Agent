# -*- coding: utf-8 -*-
"""
栅格操作工具

提供对栅格图层的基本操作：
- 获取栅格统计信息
- 导出栅格
- 重采样
"""

from typing import Any, Dict, Optional


def get_raster_stats(layer_id: str, band: Optional[int] = 1) -> dict:
    """
    获取栅格图层的统计信息。

    :param layer_id: 图层 ID
    :param band: 波段号（默认 1）
    :return: 统计信息
    """
    from .common import get_layer, is_raster

    layer, error = get_layer(layer_id)
    if error:
        return error

    # 检查是否为栅格图层
    if not is_raster(layer):
        return {'error': f'图层不是栅格类型: {layer_id}'}

    try:
        provider = layer.dataProvider()
        # 校验波段范围
        band_count = provider.bandCount()
        if band is None or band < 1 or band > band_count:
            return {'error': f'波段号无效: {band}（图层共 {band_count} 个波段）'}

        stats = _band_statistics(provider, band)
        return {
            'success': True,
            'layer': layer_id,
            'band': band,
            'stats': stats,
            'extent': layer.extent().toString(),
            'crs': layer.crs().authid(),
            'width': layer.width(),
            'height': layer.height(),
        }
    except Exception as e:
        return {'error': f'获取统计信息失败: {str(e)}'}


def _band_statistics(provider, band: int) -> dict:
    """
    通过 provider.bandStatistics 获取栅格波段统计数据。

    :param provider: 栅格数据 provider
    :param band: 波段号
    :return: 统计字典
    """
    from qgis.core import QgsRasterBandStats

    stats = provider.bandStatistics(band, QgsRasterBandStats.All)
    return {
        'min': stats.minimumValue,
        'max': stats.maximumValue,
        'mean': stats.mean,
        'stddev': stats.stdDev,
        'range': stats.range,
        'sum': stats.sum,
        'count': stats.elementCount,
    }


def reclassify_raster(layer_id: str, output_path: str,
                      reclassification: dict) -> dict:
    """
    重分类栅格（调用 Processing 算法）。

    :param layer_id: 栅格图层 ID
    :param output_path: 输出路径
    :param reclassification: 重分类规则
        示例: {"ranges": [[0, 100, 1], [100, 200, 2], [200, 9999, 3]]}
    :return: 操作结果
    """
    from .common import get_layer

    layer, error = get_layer(layer_id)
    if error:
        return error

    # 将重分类规则展平为 native:reclassifybytable 所需的扁平列表
    # ranges: [[min, max, value], ...] → [min, max, value, min, max, value, ...]
    ranges = reclassification.get('ranges', []) if reclassification else []
    table = []
    for r in ranges:
        table.extend(r)

    # 构建算法参数（算法 ID 用冒号分隔，参数名为算法实际定义）
    params = {
        'INPUT_RASTER': layer,
        'RASTER_BAND': 1,
        'TABLE': table,
        'NODATA_FOR_MISSING': False,
        'NO_DATA': -9999,
        'RANGE_BOUNDARIES': 0,
        'DATA_TYPE': 5,  # Float32
        'OUTPUT': output_path,
    }

    try:
        from qgis import processing
        result = processing.run('native:reclassifybytable', params)
        return {'success': True, 'output': result}
    except Exception as e:
        return {'error': f'重分类失败: {str(e)}'}


def rasterize(layer_id: str, output_path: str,
              field: Optional[str] = None,
              target_extent: Optional[str] = None,
              cell_size: float = 30.0) -> dict:
    """
    栅格化矢量图层（gdal:rasterize）。

    :param layer_id: 矢量图层 ID
    :param output_path: 输出栅格路径
    :param field: 用于赋值的属性字段名（不指定则全部烧录为 burn 值 1）
    :param target_extent: 目标范围 "xmin,xmax,ymin,ymax"（不指定则用图层范围）
    :param cell_size: 像元大小（地图单位）
    :return: 操作结果
    """
    from .common import get_layer

    layer, error = get_layer(layer_id)
    if error:
        return error

    # gdal:rasterize 的 EXTENT 期望 "xmin,xmax,ymin,ymax" 格式
    if target_extent:
        extent = target_extent
    else:
        e = layer.extent()
        extent = f'{e.xMinimum()},{e.xMaximum()},{e.yMinimum()},{e.yMaximum()}'

    # 构建 gdal:rasterize 参数
    params = {
        'INPUT': layer,
        'FIELD': field or '',     # 字段名字符串；为空时配合 BURN 使用固定值
        'BURN': 1,
        'UNITS': 1,               # 1 = 地理单位（像元大小按地图单位）
        'WIDTH': cell_size,
        'HEIGHT': cell_size,
        'EXTENT': extent,
        'NODATA': 0,
        'DATA_TYPE': 5,           # Float32
        'OUTPUT': output_path,
    }

    try:
        from qgis import processing
        result = processing.run('gdal:rasterize', params)
        return {'success': True, 'output': result}
    except Exception as e:
        return {'error': f'栅格化失败: {str(e)}'}
