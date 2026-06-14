# -*- coding: utf-8 -*-
"""
iface 语义化工具

将 QGIS Interface (iface) 的 329 个方法封装为语义化的工具函数。
每个工具函数都是对常用 iface 调用的组合封装，降低 Agent 使用门槛。

这些工具通过 LangChain BaseTool 暴露给 Agent，
使 Agent 可以用自然语言描述需求，而不是记忆具体的 QGIS API 签名。
"""

from typing import Any, Dict, List, Optional


def list_layers():
    """
    列出当前项目中的所有图层及其关键属性。

    返回每个图层的 ID、名称、类型、CRS、要素数量和范围。

    :return: 图层信息列表
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    result = []
    for layer_id, layer in layers.items():
        info = {
            'id': layer_id,
            'name': layer.name(),
            'type': str(layer.type()),
            'provider': layer.providerType(),
            'crs': layer.crs().authid() if layer.crs().isValid() else '未设置',
            'features': layer.featureCount(),
            'extent': layer.extent().toString() if layer.extent().isValid() else '无效范围',
        }
        # 矢量图层额外信息
        if hasattr(layer, 'geometryType'):
            info['geometry_type'] = layer.geometryType().name
        if hasattr(layer, 'fields'):
            info['fields'] = [f.name() for f in layer.fields()]

        result.append(info)

    return result


def add_layer(path: str, name: Optional[str] = None, crs: Optional[str] = None):
    """
    添加图层到当前项目。

    自动检测文件格式并调用相应的 iface 方法：
    - .shp, .geojson, .gpkg 等 → addVectorLayer
    - .tif, .img, .jpg 等 → addRasterLayer
    - .geojson, .geojsonl → addVectorLayer (GeoJSON)

    :param path: 图层文件路径或 URL
    :param name: 图层名称（默认使用文件名）
    :param crs: CRS 代码（如 "EPSG:4326"），可选
    :return: 操作结果
    """
    if name is None:
        # 用 splitext 取文件名（避免含点的路径如 C:\my.data\roads.shp 被截断）
        import os
        name = os.path.splitext(os.path.basename(path))[0]

    # 扩展名判断
    ext = path.lower().split('.')[-1] if '.' in path else ''
    vector_exts = {
        'shp', 'geojson', 'json', 'gpkg', 'kml', 'kmz',
        'csv', 'dbf', 'fgb', 'mvt', 'sqlite', 'sqlitedb'
    }
    raster_exts = {
        'tif', 'tiff', 'img', 'jpg', 'jpeg', 'png', 'bmp',
        'ecw', 'mrw', 'crw', 'raw', 'hdr', 'asc', 'grd'
    }

    try:
        if ext in vector_exts:
            result = _add_vector_layer(path, name, crs)
        elif ext in raster_exts:
            result = _add_raster_layer(path, name)
        else:
            # 尝试作为矢量加载
            result = _add_vector_layer(path, name, crs)
    except Exception as e:
        return {'success': False, 'error': str(e)}

    return {'success': True, 'name': name, 'path': path, 'type': result}


def _add_vector_layer(path: str, name: str, crs: Optional[str] = None):
    """
    添加矢量图层。

    :param path: 文件路径
    :param name: 图层名称
    :param crs: CRS 代码
    :return: 图层 ID
    """
    from qgis.core import QgsProject, QgsVectorLayer, QgsCoordinateReferenceSystem

    layer = QgsVectorLayer(path, name, 'ogr')
    if layer.isValid():
        # 若指定了 crs，显式设置图层 CRS（旧实现把 crs 拼进字符串却从未生效）
        if crs:
            crs_obj = QgsCoordinateReferenceSystem(crs)
            if crs_obj.isValid():
                layer.setCrs(crs_obj)
        QgsProject.instance().addMapLayer(layer)
        # 缩放到图层范围
        iface = _get_iface()
        if iface:
            iface.zoomToLayer(layer)
        return 'vector'
    else:
        raise Exception(f'无法加载矢量图层: {path}')


def _add_raster_layer(path: str, name: str):
    """
    添加栅格图层。

    :param path: 文件路径
    :param name: 图层名称
    :return: 图层 ID
    """
    from qgis.core import QgsProject, QgsRasterLayer

    layer = QgsRasterLayer(path, name)
    if layer.isValid():
        QgsProject.instance().addMapLayer(layer)
        return 'raster'
    else:
        raise Exception(f'无法加载栅格图层: {path}')


def remove_layer(layer_id: str):
    """
    从项目中移除图层。

    :param layer_id: 图层 ID
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    if layer_id in project.mapLayers():
        project.removeMapLayer(layer_id)
        return {'success': True, 'removed': layer_id}
    return {'success': False, 'error': f'图层不存在: {layer_id}'}


def get_layer_info(layer_id: str) -> dict:
    """
    获取图层的详细信息。

    :param layer_id: 图层 ID
    :return: 图层详细信息字典
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    layer = layers[layer_id]
    info = {
        'id': layer_id,
        'name': layer.name(),
        'type': layer.type().name if hasattr(layer.type(), 'name') else str(layer.type()),
        'provider': layer.providerType(),
        'crs': layer.crs().authid() if layer.crs().isValid() else '未设置',
        'features': layer.featureCount(),
        'extent': layer.extent().toString() if layer.extent().isValid() else '无效',
    }

    # 矢量图层详情
    if hasattr(layer, 'fields'):
        info['fields'] = [
            {'name': f.name(), 'type': f.typeName(), 'length': f.length()}
            for f in layer.fields()
        ]

    # 要素属性表（前 5 条）
    if hasattr(layer, 'getFeatures'):
        try:
            attrs_list = []
            for i, feat in enumerate(layer.getFeatures()):
                if i >= 5:
                    break
                attrs_list.append(feat.attributes())
            info['sample_attributes'] = attrs_list
        except Exception:
            pass

    return info


def zoom_to_layer(layer_id: str):
    """
    将画布缩放到指定图层。

    :param layer_id: 图层 ID
    :return: 操作结果
    """
    iface = _get_iface()
    if iface is None:
        return {'error': '无法获取 iface 对象'}

    project = QgsProjectClass()
    layers = project.mapLayers()
    if layer_id not in layers:
        return {'error': f'图层不存在: {layer_id}'}

    iface.zoomToLayer(layers[layer_id])
    return {'success': True, 'layer': layer_id}


def zoom_to_extent(extent: str):
    """
    将画布缩放到指定范围。

    :param extent: 范围字符串 "xmin,ymin,xmax,ymax"
    :return: 操作结果
    """
    iface = _get_iface()
    if iface is None:
        return {'error': '无法获取 iface 对象'}

    try:
        parts = extent.split(',')
        from qgis.core import QgsRectangle
        rect = QgsRectangle(float(parts[0]), float(parts[1]),
                           float(parts[2]), float(parts[3]))
        iface.mapCanvas().setExtent(rect)
        iface.mapCanvas().refresh()
        return {'success': True, 'extent': extent}
    except Exception as e:
        return {'error': f'范围解析失败: {str(e)}'}


def get_canvas_extent() -> str:
    """
    获取当前画布范围。

    :return: 范围字符串
    """
    iface = _get_iface()
    if iface is None:
        return '无法获取 iface 对象'

    extent = iface.mapCanvas().extent()
    return extent.toString()


def zoom_full():
    """
    缩放到全图范围。

    :return: 操作结果
    """
    iface = _get_iface()
    if iface is None:
        return {'error': '无法获取 iface 对象'}

    iface.zoomFull()
    return {'success': True}


def get_project_info() -> dict:
    """
    获取项目信息。

    :return: 项目信息字典
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()
    layers = project.mapLayers()

    return {
        'layers': len(layers),
        'crs': project.crs().authid() if project.crs().isValid() else '未设置',
        'ellipsoid': project.ellipsoid(),
        'file_path': project.filePath(),
        'dirty': project.isDirty(),
        'layer_list': [
            {'id': lid, 'name': lname.name(), 'type': lname.type().name}
            for lid, lname in layers.items()
        ],
    }


def save_project(path: Optional[str] = None):
    """
    保存当前项目。

    :param path: 保存路径（可选。不传则覆盖保存；传入则另存为指定路径）
    :return: 操作结果
    """
    from qgis.core import QgsProject

    project = QgsProject.instance()

    if path:
        # 另存为指定路径（先记录原文件名，失败时回滚，避免留下脏的项目文件名）
        old_name = project.fileName()
        project.setFileName(path)
        if project.write():
            return {'success': True, 'path': path}
        project.setFileName(old_name)
        return {'error': f'项目另存为失败: {path}'}
    else:
        # 覆盖保存
        if project.fileName():
            if project.write():
                return {'success': True, 'path': project.fileName()}
            return {'error': '项目保存失败'}
        else:
            return {'error': '项目未保存过，请指定保存路径'}


def new_project():
    """
    创建新项目。

    :return: 操作结果
    """
    iface = _get_iface()
    if iface:
        iface.newProject()
        return {'success': True}
    return {'error': '无法获取 iface 对象'}


def take_screenshot(path: str):
    """
    导出地图画布为图片。

    :param path: 输出文件路径
    :return: 操作结果
    """
    iface = _get_iface()
    if iface is None:
        return {'error': '无法获取 iface 对象'}

    try:
        # QgsMapCanvas 没有 renderToImage；使用 saveAsImage 导出，并检查结果
        ok = iface.mapCanvas().saveAsImage(path)
        # 部分版本 saveAsImage 返回 None；以文件是否生成作为兜底判断
        import os
        if ok is False or (ok is None and not os.path.exists(path)):
            return {'error': f'截图保存失败: {path}'}
        return {'success': True, 'path': path}
    except Exception as e:
        return {'error': f'截图失败: {str(e)}'}


def change_crs(epsg_code: int):
    """
    更改项目 CRS。

    :param epsg_code: EPSG 代码（如 4326）
    :return: 操作结果
    """
    from qgis.core import QgsProject, QgsCoordinateReferenceSystem

    project = QgsProject.instance()
    # 使用 fromEpsgId 构造（createFromId + EpsgCrsId 为已废弃 API）
    crs = QgsCoordinateReferenceSystem.fromEpsgId(epsg_code)

    if crs.isValid():
        project.setCrs(crs)
        return {'success': True, 'crs': f'EPSG:{epsg_code}'}
    return {'error': f'无效的 CRS: EPSG:{epsg_code}'}


# === 延迟导入辅助函数 ===

def _get_iface():
    """
    获取 QGIS 接口对象（延迟导入，避免在非插件环境中出错）。

    :return: QgisInterface 实例或 None
    """
    try:
        from qgis.utils import iface
        return iface
    except ImportError:
        return None


def QgsProjectClass():
    """延迟导入 QgsProject，避免在非插件环境中出错。"""
    from qgis.core import QgsProject
    return QgsProject.instance()
