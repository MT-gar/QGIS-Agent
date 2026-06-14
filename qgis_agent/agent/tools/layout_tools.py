# -*- coding: utf-8 -*-
"""
打印布局工具

提供 QGIS 打印布局（Print Layout）的操作能力：
- 创建/导出打印布局
- 列出已有布局

注：add_layout_item 涉及大量项目类型与定位细节，当前未实现，
诚实返回 success=False，由 LLM 改用 qgis_api_call 处理。
"""

from typing import Optional, List, Dict


# 纸张尺寸（毫米，宽 x 高，竖版）
_PAGE_SIZES_MM = {
    'A4': (210, 297),
    'A3': (297, 420),
    'A2': (420, 594),
    'A1': (594, 841),
    'A0': (841, 1189),
}


def create_layout(name: str, size: str = 'A4', orientation: str = 'portrait') -> dict:
    """
    创建新的打印布局并加入项目的布局管理器。

    :param name: 布局名称
    :param size: 纸张大小（'A4', 'A3', 'A2', 'A1', 'A0'）
    :param orientation: 方向（'portrait' 竖版, 'landscape' 横版）
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsPrintLayout, QgsLayoutSize, QgsUnitTypes

        project = QgsProject.instance()
        manager = project.layoutManager()

        # 同名布局已存在则报错，避免重复
        if manager.layoutByName(name) is not None:
            return {'error': f'同名布局已存在: {name}'}

        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(name)

        # 设置纸张尺寸与方向
        w, h = _PAGE_SIZES_MM.get(size.upper(), _PAGE_SIZES_MM['A4'])
        if orientation.lower() == 'landscape':
            w, h = h, w
        page = layout.pageCollection().pages()[0]
        page.setPageSize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))

        manager.addLayout(layout)
        return {
            'success': True,
            'name': name,
            'size': size,
            'orientation': orientation,
        }
    except Exception as e:
        return {'error': f'创建布局失败: {str(e)}'}


def add_layout_item(layout_name: str, item_type: str,
                    position: dict, size: dict) -> dict:
    """
    向打印布局添加项目（当前未实现）。

    :return: success=False，并提示改用 qgis_api_call
    """
    return {
        'success': False,
        'error': 'add_layout_item 暂未实现',
        'hint': (
            '请改用 qgis_api_call 操作 QgsLayoutItemMap / QgsLayoutItemLegend 等，'
            '并通过 layout.addLayoutItem(item) 添加'
        ),
    }


def export_layout_as_image(layout_name: str, output_path: str,
                           dpi: int = 300) -> dict:
    """
    将打印布局导出为图片。

    :param layout_name: 布局名称
    :param output_path: 输出文件路径（.png, .jpg）
    :param dpi: 分辨率
    :return: 操作结果
    """
    try:
        from qgis.core import QgsProject, QgsLayoutExporter

        project = QgsProject.instance()
        layout = project.layoutManager().layoutByName(layout_name)
        if layout is None:
            return {'error': f'布局不存在: {layout_name}'}

        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = dpi

        result = exporter.exportToImage(output_path, settings)
        if result == QgsLayoutExporter.Success:
            return {'success': True, 'layout': layout_name,
                    'output': output_path, 'dpi': dpi}
        return {'error': f'布局导出失败（错误码 {result}）'}
    except Exception as e:
        return {'error': f'布局导出失败: {str(e)}'}


def list_layouts() -> List[dict]:
    """
    列出当前项目中的所有打印布局。

    :return: 布局列表
    """
    try:
        from qgis.core import QgsProject

        manager = QgsProject.instance().layoutManager()
        # 正确入口为 layoutManager().printLayouts()；QgsPrintLayout 无 id()
        return [{'name': lay.name()} for lay in manager.printLayouts()]
    except Exception as e:
        return [{'error': f'列出布局失败: {str(e)}'}]
