<div align="center">

# QGIS Agent

**用自然语言驱动 QGIS —— AI Agent 插件**

[![QGIS](https://img.shields.io/badge/QGIS-4.0+-5B9A3D?style=for-the-badge&logo=qgis&logoColor=white)](https://qgis.org)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=for-the-badge)](https://www.gnu.org/licenses/gpl-3.0)

一个嵌入 QGIS 的 AI 聊天助手。用中文（或英文）描述你想做什么，Agent 自动调用 QGIS 的全部能力来完成。

<br/>

```
用户：帮我把 rivers.shp 做 500 米缓冲区，然后裁剪到 study_area 范围内

Agent：好的，我来分步完成：
  1. 查询 rivers.shp 和 study_area 的图层信息 ✓
  2. 执行 native:buffer 算法，距离 500 米 ✓
  3. 执行 native:clip 算法，用 study_area 裁剪缓冲区结果 ✓
  4. 已将结果添加到项目中，图层名为 "rivers_buffer_clipped"
```

</div>

---

## ✨ 特性

| 能力 | 说明 |
|------|------|
| **自然语言交互** | 在聊天面板中用日常语言描述任务，Agent 自动规划和执行 |
| **35+ 内置工具** | 涵盖图层管理、空间分析、要素编辑、表达式计算、网络服务、打印布局等 |
| **Processing 算法** | 直接调用 QGIS 全部 Processing 算法（GDAL、GRASS、SAGA、原生） |
| **QGIS API 桥接** | 自动发现 qgis.core（1400+ 类）和 qgis.gui（700+ 类），支持链式调用 |
| **多 LLM 后端** | 支持 OpenAI、Anthropic、Ollama（本地模型），通过 litellm 统一接口 |
| **安全控制** | 危险操作弹窗确认、速率限制、执行日志 |
| **任务控制** | 运行中支持暂停/恢复和取消 |
| **会话管理** | 多会话切换、历史持久化 |

---

## 🚀 安装

### 前置条件

- QGIS 4.0+
- Python 3.10+（QGIS 自带）
- LLM API Key（OpenAI / Anthropic）或本地 Ollama

### 步骤

**1. 安装 Python 依赖**

在 QGIS 的 Python 环境中安装：

```bash
# 方式一：使用 QGIS 内置的 pip
# 打开 QGIS → 插件 → Python 控制台，执行：
import pip
pip.main(['install', 'langchain-core', 'litellm'])

# 方式二：命令行（找到 QGIS 的 Python 路径）
# Windows 示例：
"C:\OSGeo4W\apps\Python312\python.exe" -m pip install langchain-core litellm
```

> **提示**：如果只用 OpenAI，也可以直接 `pip install openai` 代替 litellm。

**2. 安装插件**

```bash
# 方式一：下载 release zip，解压到 QGIS 插件目录
# Windows: %APPDATA%\QGIS\QGIS4\profiles\default\python\plugins\qgis-agent\
# Linux:   ~/.local/share/QGIS/QGIS4/profiles/default/python/plugins/qgis-agent/
# macOS:   ~/Library/Application Support/QGIS/QGIS4/profiles/default/python/plugins/qgis-agent/

# 方式二：从源码安装
git clone https://github.com/your-org/qgis-agent.git
cd qgis-agent
python qgis_agent/pack.py
# 将生成的 dist/qgis-agent.zip 通过 QGIS 插件管理器安装
```

**3. 启用插件**

QGIS → 插件 → 管理并安装插件 → 已安装 → 勾选 **QGIS Agent**

---

## 📖 使用

### 基本操作

1. 启用插件后，右侧出现 **QGIS Agent** 面板
2. 在顶部配置 LLM（提供商、模型、API Key）
3. 在底部输入框输入自然语言指令，回车或点击"发送"

### 示例

```
# 图层管理
"列出当前项目所有图层"
"加载 C:/data/dem.tif 到项目中"
"删除名为 temp 的图层"

# 空间分析
"对 roads 做 100 米缓冲区"
"用 admin_boundary 裁剪 buildings"
"计算 buildings 和 flood_zone 的交集"

# 数据查询
"查询 rivers 中 FCODE 等于 'H1200' 的要素"
"统计 population 字段的总和与平均值"
"计算每个地块的面积并写入 area_ha 字段"

# 表达式计算
"用 $area 计算所有地块面积"
"把 name 字段全部转为大写"
"列出所有可用的表达式函数"

# 网络服务
"添加 OpenStreetMap 底图"
"添加 WMS 服务 https://example.com/wms，图层名为 temperature"

# Processing 算法
"列出所有可用的 Processing 算法"
"执行 native:reprojectlayer 把图层转为 WGS84"
```

### 任务控制

Agent 运行期间，输入区域会显示：

- **暂停** — 暂停当前任务，点击"恢复"继续
- **停止** — 立即取消当前任务

### 安全机制

| 机制 | 说明 |
|------|------|
| 危险操作确认 | 删除图层、删除要素、执行代码等操作会弹窗确认 |
| 速率限制 | 每分钟最多 60 次工具调用 |
| 重复调用检测 | 同一工具+参数重复 3 次自动终止 |
| 最大步数限制 | 单次任务最多 20 步工具调用 |

---

## 🏗️ 架构

```
qgis_agent/
├── __init__.py              # 插件入口
├── plugin.py                # QGIS 插件主类
├── agent/
│   ├── loop.py              # Agent 核心循环（工具调用驱动）
│   ├── client.py            # LLM 客户端（OpenAI/Anthropic/Ollama）
│   ├── provider.py          # 工具注册工厂（35+ 工具）
│   ├── session.py           # 会话管理（多会话 + 持久化）
│   ├── safety.py            # 安全控制（确认/限流/日志）
│   ├── chat/
│   │   ├── chat_panel.py    # 聊天 UI 面板
│   │   └── message_renderer.py  # 消息格式化
│   └── tools/
│       ├── qgis_bridge.py   # QGIS API 通用桥接器
│       ├── iface_tools.py   # iface 语义化工具（12 个）
│       ├── processing_bridge.py  # Processing 算法桥接
│       ├── layer_tools.py   # 图层/要素操作（5 个）
│       ├── edit_tools.py    # 编辑操作（6 个）
│       ├── expression_tools.py   # 表达式与字段计算（4 个）
│       ├── raster_tools.py  # 栅格操作
│       ├── network_tools.py # 网络服务（5 个）
│       ├── plugin_tools.py  # 插件集成 + Python 代码执行
│       └── layout_tools.py  # 打印布局
└── icons/
    └── agent.svg
```

### 核心流程

```
用户输入
    │
    ▼
┌──────────────────────────────────────────────┐
│              Agent 循环 (loop.py)             │
│                                              │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐ │
│   │ LLM 决策 │───→│ 工具执行 │───→│ 结果回灌 │ │
│   └─────────┘    └─────────┘    └─────────┘ │
│        ▲                                 │    │
│        └─────────────────────────────────┘    │
│                  直到任务完成                   │
└──────────────────────────────────────────────┘
    │
    ▼
  最终回复
```

---

## ⚙️ 配置

在聊天面板顶部可实时配置：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| **LLM 提供商** | openai / anthropic / ollama | openai |
| **模型** | 模型名称 | gpt-4o |
| **端点** | 自定义 base_url（可选） | 官方默认 |
| **API Key** | 仅存于内存，不写入磁盘 | — |

### 使用本地模型（Ollama）

```bash
# 1. 安装 Ollama 并拉取模型
ollama pull llama3.1

# 2. 在 QGIS Agent 面板中配置
#    提供商: ollama
#    模型: llama3.1
#    端点: http://localhost:11434
```

### 添加新工具

1. 在 `tools/` 下编写函数（带类型注解和文档字符串）
2. 在 `provider.py` 中用 `StructuredTool.from_function()` 注册
3. Agent 自动获得新工具的调用能力

---

## 📊 工具清单

<details>
<summary><b>iface 工具（12 个）</b> — 图层管理、画布操作、项目管理</summary>

| 工具 | 说明 |
|------|------|
| `list_layers` | 列出所有图层信息 |
| `add_layer` | 添加矢量/栅格图层 |
| `remove_layer` | 移除图层 |
| `get_layer_info` | 获取图层详细信息 |
| `zoom_to_layer` | 缩放到图层范围 |
| `zoom_full` | 缩放到全图 |
| `get_canvas_extent` | 获取画布范围 |
| `get_project_info` | 获取项目信息 |
| `save_project` | 保存项目 |
| `new_project` | 新建项目 |
| `take_screenshot` | 导出地图图片 |
| `change_crs` | 更改坐标系 |

</details>

<details>
<summary><b>Processing 算法工具（3 个）</b> — GDAL / GRASS / SAGA / 原生</summary>

| 工具 | 说明 |
|------|------|
| `list_algorithms` | 列出所有算法 |
| `get_algorithm_info` | 获取算法详情 |
| `run_algorithm` | 执行算法 |

</details>

<details>
<summary><b>图层工具（5 个）</b> — 创建、查询、导出</summary>

| 工具 | 说明 |
|------|------|
| `create_vector_layer` | 创建内存矢量图层 |
| `add_field` | 添加字段 |
| `query_features` | 查询要素 |
| `select_features` | 选择要素 |
| `save_layer_as` | 导出图层 |

</details>

<details>
<summary><b>编辑工具（6 个）</b> — 要素增删改</summary>

| 工具 | 说明 |
|------|------|
| `start_editing` | 开始编辑 |
| `stop_editing` | 停止编辑 |
| `add_feature` | 添加要素 |
| `delete_feature` | 删除要素 |
| `edit_attribute` | 修改属性 |
| `delete_selected_features` | 删除选中要素 |

</details>

<details>
<summary><b>表达式工具（4 个）</b> — QGIS 表达式引擎</summary>

| 工具 | 说明 |
|------|------|
| `evaluate_expression` | 执行表达式计算 |
| `validate_expression` | 验证表达式语法 |
| `list_expression_functions` | 列出可用函数 |
| `field_statistics` | 字段统计 |

</details>

<details>
<summary><b>网络工具（5 个）</b> — WMS / WFS / XYZ / ArcGIS</summary>

| 工具 | 说明 |
|------|------|
| `add_wms_layer` | 添加 WMS 图层 |
| `add_wfs_layer` | 添加 WFS 图层 |
| `add_xyz_layer` | 添加 XYZ 瓦片图层 |
| `add_arcgis_map_service` | 添加 ArcGIS 服务 |
| `get_network_response` | HTTP 请求 |

</details>

<details>
<summary><b>其他工具（7 个）</b> — API 桥接、代码执行、栅格、布局</summary>

| 工具 | 说明 |
|------|------|
| `qgis_api_call` | 调用任意 QGIS API（链式调用） |
| `qgis_list_classes` | 列出所有 QGIS 类 |
| `qgis_get_class_doc` | 获取类文档 |
| `execute_python_code` | 执行 Python 代码 |
| `format_table` | 格式化表格输出 |
| `get_raster_stats` | 栅格统计 |
| `list_installed_plugins` | 列出已安装插件 |

</details>

---

## 📝 更新日志

### v0.1.1 (2026-06-13)

- 新增任务暂停/恢复和取消功能
- Agent 循环中增加 3 个安全断点检查

### v0.1.0 (2026-06-11)

- 初始版本
- 35+ 内置工具，覆盖 QGIS 核心功能
- 多 LLM 后端支持（OpenAI / Anthropic / Ollama）
- 安全控制（危险操作确认、速率限制、执行日志）
- 会话管理（多会话切换、历史持久化）

---

## 📄 许可证

[GPL-3.0](LICENSE)

---

<div align="center">

**[报告 Bug](https://github.com/your-org/qgis-agent/issues)** · **[功能建议](https://github.com/your-org/qgis-agent/issues/new)** · **[贡献指南](CONTRIBUTING.md)**

</div>
