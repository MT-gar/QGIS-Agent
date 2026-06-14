# -*- coding: utf-8 -*-
"""
网络服务工具

提供 QGIS 网络服务相关的操作：
- WMS/WFS/XYZ 图层添加
- 网络请求（通过 QgsNetworkAccessManager）
- 元数据搜索（MetaSearch）
"""

from typing import Optional, Dict


def add_wms_layer(url: str, layers: str, name: Optional[str] = None,
                  crs: Optional[str] = 'EPSG:4326') -> dict:
    """
    添加 WMS（Web Map Service）图层。

    :param url: WMS 服务 URL
    :param layers: 图层名称（逗号分隔，如 "layer1,layer2"）
    :param name: 图层显示名称
    :param crs: CRS 代码
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsRasterLayer

        if name is None:
            name = f'WMS: {layers}'

        # 构建 WMS URL
        wms_url = f'url={url}&type=wms&version=1.3.0&crs={crs}&layers={layers}&format=image/png'

        layer = QgsRasterLayer(wms_url, name, 'wms')
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {'success': True, 'layer_id': layer.id(), 'name': layer.name()}
        else:
            return {'error': f'无法加载 WMS 图层: {url}'}
    except Exception as e:
        return {'error': f'WMS 加载失败: {str(e)}'}


def add_wfs_layer(url: str, layer_name: str,
                  name: Optional[str] = None,
                  crs: Optional[str] = 'EPSG:4326',
                  limit: int = 2000) -> dict:
    """
    添加 WFS（Web Feature Service）图层。

    :param url: WFS 服务 URL
    :param layer_name: WFS 中的图层名称
    :param name: 图层显示名称
    :param crs: CRS 代码
    :param limit: 最大要素数限制
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsVectorLayer

        if name is None:
            name = f'WFS: {layer_name}'

        # 构建 WFS URI（要素数量上限的 provider 参数名为 maxNumFeatures）
        wfs_url = (
            f'url={url}&typename={layer_name}&crs={crs}'
            f'&ignoreShapeAggregates=1&maxNumFeatures={limit}&srsname={crs}'
        )

        layer = QgsVectorLayer(wfs_url, name, 'wfs')
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {'success': True, 'layer_id': layer.id(), 'name': layer.name()}
        else:
            return {'error': f'无法加载 WFS 图层: {url}'}
    except Exception as e:
        return {'error': f'WFS 加载失败: {str(e)}'}


def add_xyz_layer(url: str, name: Optional[str] = None,
                  crs: str = 'EPSG:3857') -> dict:
    """
    添加 XYZ（Tile）图层（如 OpenStreetMap、Google Maps 等）。

    :param url: 瓦片服务 URL（支持 {x}, {y}, {z} 占位符）
    :param name: 图层显示名称
    :param crs: CRS 代码
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsRasterLayer

        if name is None:
            name = 'XYZ Layer'

        xyz_url = f'url={url}&type=xyz&crs={crs}&zmin=0&zmax=19&format=png'

        layer = QgsRasterLayer(xyz_url, name, 'xyz')
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {'success': True, 'layer_id': layer.id(), 'name': layer.name()}
        else:
            return {'error': f'无法加载 XYZ 图层: {url}'}
    except Exception as e:
        return {'error': f'XYZ 加载失败: {str(e)}'}


def get_network_response(url: str, method: str = 'GET',
                         headers: Optional[dict] = None,
                         timeout: int = 30) -> dict:
    """
    通过 QgsNetworkAccessManager 发送 HTTP 请求。

    使用 QGIS 内置的网络管理器，支持认证和代理设置。

    :param url: 请求 URL
    :param method: HTTP 方法（GET/POST）
    :param headers: 请求头字典
    :param timeout: 超时时间（秒）
    :return: 响应结果
    """
    try:
        from qgis.core import QgsNetworkAccessManager
        from qgis.PyQt.QtCore import QUrl, QEventLoop, QTimer
        from qgis.PyQt.QtNetwork import QNetworkRequest

        # 构建请求（QNetworkRequest 在 QtNetwork；URL 需为 QUrl）
        request = QNetworkRequest(QUrl(url))
        if headers:
            for key, value in headers.items():
                request.setRawHeader(key.encode(), str(value).encode())

        manager = QgsNetworkAccessManager.instance()
        if method.upper() == 'POST':
            reply = manager.post(request, b'')
        else:
            reply = manager.get(request)

        # 用事件循环等待完成，并用定时器强制超时，避免无上限忙等死循环阻塞 UI
        loop = QEventLoop()
        reply.finished.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(max(1, timeout) * 1000)
        loop.exec()

        try:
            # 超时（定时器先触发，请求仍未完成）
            if not reply.isFinished():
                reply.abort()
                return {'error': f'请求超时（{timeout}s）', 'url': url}

            if reply.error() != reply.NetworkError.NoError:
                return {'error': f'请求失败: {reply.errorString()}', 'url': url}

            body = reply.readAll().data().decode('utf-8', errors='replace')
            status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            return {
                'success': True,
                'status_code': int(status_code) if status_code else None,
                'body': body[:10000],  # 限制返回长度
                'url': url,
            }
        finally:
            # 释放 reply，避免资源泄漏
            reply.deleteLater()

    except Exception as e:
        return {'error': f'网络请求失败: {str(e)}'}


def search_csw(url: str, keyword: str, max_records: int = 10) -> dict:
    """
    通过 CSW（Catalog Service for the Web）搜索元数据。

    :param url: CSW 服务 URL
    :param keyword: 搜索关键词
    :param max_records: 最大记录数
    :return: 搜索结果
    """
    try:
        import requests

        params = {
            'service': 'CSW',
            'version': '2.0.2',
            'request': 'GetRecords',
            'typename': 'csw:Record',
            'resultType': 'results',
            'maxRecords': max_records,
            'elementSetName': 'full',
            'query': f'{{http://www.opengis.net/def/query/0/0/BasicQuery}}<Constraint version="1.1.0" xmlns="http://www.opengis.net/owc/1.0"><Text><Value>{keyword}</Value></Text></Constraint>',
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        return {
            'success': True,
            'url': url,
            'keyword': keyword,
            'record_count': max_records,
            'xml_response': response.text[:5000],
            'message': 'CSW 查询成功，返回 XML 格式的元数据',
        }
    except ImportError:
        return {'error': 'requests 模块不可用', 'hint': '使用 qgis_api_call("QgsNetworkAccessManager...") 替代'}
    except Exception as e:
        return {'error': f'CSW 搜索失败: {str(e)}'}


def add_arcgis_map_service(url: str, layer_id: Optional[str] = None,
                           name: Optional[str] = None) -> dict:
    """
    添加 ArcGIS Map Server 图层。

    :param url: ArcGIS Map Server URL
    :param layer_id: 图层编号（如 "0", "0,1,2"）
    :param name: 图层显示名称
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsRasterLayer

        if name is None:
            name = 'ArcGIS Map Server'

        arcgis_url = f'url={url}&type=arcgismapserver&layers={layer_id or "0"}&format=png'

        layer = QgsRasterLayer(arcgis_url, name, 'arcgismapserver')
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            return {'success': True, 'layer_id': layer.id(), 'name': layer.name()}
        else:
            return {'error': f'无法加载 ArcGIS 图层: {url}'}
    except Exception as e:
        return {'error': f'ArcGIS 加载失败: {str(e)}'}
