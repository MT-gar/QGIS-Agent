# -*- coding: utf-8 -*-
"""
Agent 提供者（工厂）

负责创建和配置 LangChain Agent，将所有 QGIS 工具注册为 Agent 可用的工具。

Agent 通过 ReAct 循环自动决定调用哪些工具来完成任务。
"""

from typing import List, Optional

from langchain_core.tools import BaseTool


def create_qgis_tools(qgis_bridge, iface) -> List[BaseTool]:
    """
    创建所有 QGIS 工具列表，供 Agent 使用。

    将 iface_tools、processing_bridge、layer_tools 等模块中的所有
    函数封装为 LangChain BaseTool。

    :param qgis_bridge: QGisAPIBridge 实例
    :param iface: QGIS 接口对象
    :return: 工具列表
    """
    # StructuredTool 在新版 langchain 已迁到 langchain_core.tools；
    # 从 langchain.tools 导入在新版会失败，统一从 langchain_core 导入。
    from langchain_core.tools import StructuredTool

    # 导入各工具模块的函数
    from .tools import iface_tools, processing_bridge, layer_tools
    from .tools import edit_tools, raster_tools, qgis_bridge as qb
    from .tools import expression_tools, network_tools, plugin_tools
    from .tools import layout_tools
    from .chat import message_renderer

    tools = []

    # === iface_tools 工具 ===
    tools.append(StructuredTool.from_function(
        func=iface_tools.list_layers,
        name='list_layers',
        description='列出当前项目中所有图层的详细信息，包括图层ID、名称、类型、CRS、要素数量和范围。用于了解项目中有哪些数据。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.add_layer,
        name='add_layer',
        description='添加图层到当前项目。支持矢量图层（.shp, .geojson, .gpkg等）和栅格图层（.tif, .img, .jpg等）。自动检测文件格式。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.remove_layer,
        name='remove_layer',
        description='从项目中移除指定图层。需要提供图层ID。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.get_layer_info,
        name='get_layer_info',
        description='获取指定图层的详细信息，包括字段定义、要素属性表（前5条）、几何类型、CRS等。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.zoom_to_layer,
        name='zoom_to_layer',
        description='将地图画布缩放到指定图层范围。需要图层ID。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.zoom_full,
        name='zoom_full',
        description='将地图画布缩放到全图范围（所有图层的最大范围）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.get_canvas_extent,
        name='get_canvas_extent',
        description='获取当前地图画布的范围（xmin, ymin, xmax, ymax）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.get_project_info,
        name='get_project_info',
        description='获取当前项目的综合信息：图层数量、CRS、Ellipsoid、文件路径、图层列表。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.save_project,
        name='save_project',
        description='保存当前QGIS项目。可以指定保存路径，不指定则覆盖保存。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.new_project,
        name='new_project',
        description='创建新的QGIS项目（清空当前项目）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.take_screenshot,
        name='take_screenshot',
        description='将当前地图画布导出为图片文件。需要指定输出文件路径。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=iface_tools.change_crs,
        name='change_crs',
        description='更改项目的坐标系（CRS）。需要提供EPSG代码（如4326表示WGS84）。',
        handle_tool_error=True,
    ))

    # === Processing 算法工具 ===
    tools.append(StructuredTool.from_function(
        func=processing_bridge.list_algorithms,
        name='list_algorithms',
        description='列出所有可用的Processing算法，按provider分类。包含qgis原生、GDAL、GRASS、SAGA等算法。支持按provider过滤。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=processing_bridge.get_algorithm_info,
        name='get_algorithm_info',
        description='获取指定算法的详细信息，包括参数列表（名称、类型、是否必填）、输出定义和文档。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=processing_bridge.run_algorithm,
        name='run_algorithm',
        description='执行Processing算法。需要提供算法ID（如native_buffer、gdal_rasterize等）和参数字典。自动识别图层名称。',
        handle_tool_error=True,
    ))

    # === qgis_bridge 通用工具 ===
    tools.append(StructuredTool.from_function(
        func=qb.get_bridge(iface).call,
        name='qgis_api_call',
        description='通过方法路径调用任何QGIS API。支持链式调用（如iface.mapCanvas().extent().toString()）。这是最强大的工具，可以调用qgis.core和qgis.gui中几乎所有功能。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=qb.get_bridge(iface).list_classes,
        name='qgis_list_classes',
        description='列出所有可用的QGIS类。返回qgis.core和qgis.gui中所有公开的类名。用于发现可用的API。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=qb.get_bridge(iface).get_class_doc,
        name='qgis_get_class_doc',
        description='获取指定QGIS类的文档和可用方法列表。需要提供类名（如QgsVectorLayer、QgsGeometry等）。',
        handle_tool_error=True,
    ))

    # === Layer tools ===
    tools.append(StructuredTool.from_function(
        func=layer_tools.create_vector_layer,
        name='create_vector_layer',
        description='创建新的内存矢量图层。可以指定几何类型（point/line/polygon）和字段定义。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.add_field,
        name='add_field',
        description='向矢量图层添加新字段。支持string/integer/double/boolean/date/datetime类型。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.query_features,
        name='query_features',
        description='查询矢量图层中的要素。支持SQL风格的过滤表达式，返回要素属性。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.select_features,
        name='select_features',
        description='选择图层中符合条件的要素。使用SQL风格的过滤表达式。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.save_layer_as,
        name='save_layer_as',
        description='将图层导出为不同格式。支持GeoJSON、GPKG、CSV、ESRI Shapefile等。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.get_layer_crs,
        name='get_layer_crs',
        description='获取图层的坐标系（CRS），返回如 EPSG:4326 格式的代码。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layer_tools.reproject_layer,
        name='reproject_layer',
        description='重投影图层到目标坐标系。使用 native:reprojectlayer 算法，不指定输出路径则创建临时图层。',
        handle_tool_error=True,
    ))

    # === Edit tools ===
    tools.append(StructuredTool.from_function(
        func=edit_tools.start_editing,
        name='start_editing',
        description='开始对图层进行编辑。编辑后才能添加、修改或删除要素。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.stop_editing,
        name='stop_editing',
        description='停止编辑图层。可以选择保存更改或放弃更改。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.add_feature,
        name='add_feature',
        description='向矢量图层添加新要素。需要提供属性值和可选的几何WKT字符串。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.delete_feature,
        name='delete_feature',
        description='删除图层中指定的要素。需要提供要素ID。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.edit_attribute,
        name='edit_attribute',
        description='修改要素的单个属性值。需要提供要素ID、字段名和新值。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.delete_selected_features,
        name='delete_selected_features',
        description='删除图层中所有已选择的要素。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.get_selected_features,
        name='get_selected_features',
        description='获取图层中已选择的要素信息，包括属性和数量。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=edit_tools.clear_selection,
        name='clear_selection',
        description='清除图层中的要素选择。',
        handle_tool_error=True,
    ))

    # === Raster tools ===
    tools.append(StructuredTool.from_function(
        func=raster_tools.get_raster_stats,
        name='get_raster_stats',
        description='获取栅格图层的统计信息：最小值、最大值、平均值、标准差等。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=raster_tools.reclassify_raster,
        name='reclassify_raster',
        description='重分类栅格图层。需要提供重分类规则（范围映射表），调用 native:reclassifybytable 算法。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=raster_tools.rasterize,
        name='rasterize',
        description='将矢量图层栅格化。可指定赋值字段、目标范围和像元大小，调用 gdal:rasterize 算法。',
        handle_tool_error=True,
    ))

    # === Expression tools ===
    tools.append(StructuredTool.from_function(
        func=expression_tools.evaluate_expression,
        name='evaluate_expression',
        description='在图层中对每个要素执行QGIS表达式计算。表达式支持数学运算、字符串处理、地理函数（$area, $length, x(), y()等）。返回每个要素的计算结果。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=expression_tools.validate_expression,
        name='validate_expression',
        description='验证QGIS表达式的语法正确性。在复杂表达式执行前先验证。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=expression_tools.list_available_functions,
        name='list_expression_functions',
        description='列出QGIS表达式引擎中所有可用的函数，按类别分组（数学、字符串、聚合、日期时间、地理、条件、数组、变量）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=expression_tools.field_statistics,
        name='field_statistics',
        description='计算数值字段的基本统计信息：计数、总和、平均值、中位数、标准差、最小值、最大值、范围。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=expression_tools.calculate_field,
        name='calculate_field',
        description='使用表达式进行字段计算，生成含新字段的图层。调用 native:fieldcalculator 算法，结果为新图层（原图层不变）。',
        handle_tool_error=True,
    ))

    # === Network tools ===
    tools.append(StructuredTool.from_function(
        func=network_tools.add_wms_layer,
        name='add_wms_layer',
        description='添加WMS（Web Map Service）图层到项目中。支持OGC标准的Web地图服务。需要服务URL和图层名称。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=network_tools.add_wfs_layer,
        name='add_wfs_layer',
        description='添加WFS（Web Feature Service）图层到项目中。支持OGC标准的Web要素服务，返回矢量数据。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=network_tools.add_xyz_layer,
        name='add_xyz_layer',
        description='添加XYZ瓦片图层（如OpenStreetMap、Google Maps等）到项目中。需要瓦片服务URL（支持{x},{y},{z}占位符）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=network_tools.add_arcgis_map_service,
        name='add_arcgis_map_service',
        description='添加ArcGIS Map Server图层到项目中。需要服务URL和可选的图层编号。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=network_tools.get_network_response,
        name='get_network_response',
        description='通过QGIS网络管理器发送HTTP请求。支持GET/POST，可用于访问API获取数据。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=network_tools.search_csw,
        name='search_csw',
        description='通过CSW（Catalog Service for the Web）搜索地理空间元数据。需要服务URL和搜索关键词。依赖requests库。',
        handle_tool_error=True,
    ))

    # === 消息渲染工具 ===
    tools.append(StructuredTool.from_function(
        func=message_renderer.format_table,
        name='format_table',
        description='将表格数据（二维列表）格式化为可读的 ASCII 文本表格，适用于数据展示。',
        handle_tool_error=True,
    ))

    # === Plugin tools (additional) ===
    tools.append(StructuredTool.from_function(
        func=plugin_tools.list_installed_plugins,
        name='list_installed_plugins',
        description='列出当前QGIS中所有已安装的插件信息。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=plugin_tools.execute_python_code,
        name='execute_python_code',
        description='执行自定义Python代码（通过QGIS API）。这是最强大的工具——可以编写任意Python脚本来操作QGIS的全部功能。代码中可访问QgsApplication、QgsProject、QgsVectorLayer等所有QGIS类以及iface对象。',
        handle_tool_error=True,
    ))

    # === Layout tools ===
    tools.append(StructuredTool.from_function(
        func=layout_tools.create_layout,
        name='create_layout',
        description='创建新的打印布局。可指定纸张大小（A0-A4）和方向（portrait/landscape）。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layout_tools.export_layout_as_image,
        name='export_layout_as_image',
        description='将打印布局导出为图片文件（PNG/JPG）。可指定DPI分辨率。',
        handle_tool_error=True,
    ))

    tools.append(StructuredTool.from_function(
        func=layout_tools.list_layouts,
        name='list_layouts',
        description='列出当前项目中的所有打印布局。',
        handle_tool_error=True,
    ))

    return tools
