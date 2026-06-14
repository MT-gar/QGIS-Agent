# QGIS Agent 下一阶段功能规格

## 功能概述

本次迭代需实现三大核心功能：
1. **插件智能发现与安装**：Agent 自动分析用户需求，查找并安装所需 QGIS 插件
2. **任务计划持续执行**：修复任务拆解后单步完成即停止的问题，实现任务列表持久化与自动续行
3. **QGIS 3.44 兼容性**：向下兼容低版本 QGIS API

---

## 功能一：插件智能发现与安装

### 问题描述

当前 Agent 无法自动发现和安装 QGIS 插件。当用户需求依赖特定插件时，Agent 需要手动指导用户操作。

### 目标

实现一个完整的插件生命周期管理工具链：
- 搜索 QGIS 官方插件仓库
- 分析插件元数据（名称、描述、依赖、版本兼容性）
- 下载并安装插件
- 验证安装状态
- 卸载插件（可选）

### 技术设计

#### 1.1 新增工具：`search_plugins`

```python
def search_plugins(query: str, category: str = "all", limit: int = 10) -> str:
    """
    搜索 QGIS 官方插件仓库

    Args:
        query: 搜索关键词（支持中英文）
        category: 插件分类过滤（analysis/database/web/raster/vector/等）
        limit: 返回结果数量限制

    Returns:
        JSON 格式的插件列表，包含：
        - plugin_id: 插件标识符
        - name: 显示名称
        - description: 简要描述
        - version: 最新版本
        - qgis_min_version: 最低 QGIS 版本要求
        - author: 作者
        - downloads: 下载次数
        - rating: 评分
    """
```

#### 1.2 新增工具：`install_plugin`

```python
def install_plugin(plugin_id: str, version: str = "latest") -> str:
    """
    安装指定 QGIS 插件

    Args:
        plugin_id: 插件标识符
        version: 指定版本（默认最新）

    Returns:
        安装结果，包含：
        - status: success/failed/already_installed
        - installed_path: 安装路径
        - message: 详细信息
    """
```

#### 1.3 新增工具：`list_installed_plugins`

```python
def list_installed_plugins(enabled_only: bool = False) -> str:
    """
    列出已安装的插件

    Args:
        enabled_only: 是否只显示启用的插件

    Returns:
        JSON 格式的已安装插件列表
    """
```

#### 1.4 插件仓库数据源

使用 QGIS 官方插件仓库 API：
- 主仓库：https://plugins.qgis.org/plugins/plugins.xml
- 备用：PyPI（对于纯 Python 包）

#### 1.5 安装流程

```
用户请求 → search_plugins() → 分析结果 → 确认安装 → install_plugin() → 验证 → 启用插件
```

#### 1.6 错误处理

- 网络超时：重试 3 次，间隔递增
- 版本不兼容：提供兼容版本列表
- 安装失败：回滚并报告原因
- 依赖冲突：检测并提示解决方案

---

## 功能二：任务计划持续执行

### 问题描述

当前任务拆解存在两个关键缺陷：
1. **单步终止**：LLM 完成第一个步骤后即结束当前会话，不会自动继续执行后续步骤
2. **任务列表关闭**：每个步骤完成后 TaskTreeWidget 被清空，用户无法追踪整体进度

### 根本原因

`AgentLoop.run()` 中的循环逻辑：
```python
# 当前实现（简化）
while not self._cancelled:
    response = self._call_llm()
    if response.stop_reason == "end_turn":
        break  # ← 问题：单步完成后直接退出
```

LLM 在完成一个步骤后返回 `end_turn`，但实际还有未完成的计划步骤。

### 目标

实现真正的任务计划持续执行：
- 拆解任务后自动执行所有步骤
- 每步完成后自动触发下一步
- 任务列表保持可见并实时更新
- 支持用户中途干预（暂停/跳过/修改计划）

### 技术设计

#### 2.1 任务状态机

```python
class TaskStatus(Enum):
    PENDING = "pending"      # 等待执行
    RUNNING = "running"      # 正在执行
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 执行失败
    SKIPPED = "skipped"      # 用户跳过
    PAUSED = "paused"        # 用户暂停
```

#### 2.2 修改 AgentLoop.run() 主循环

```python
def run(self, user_input: str) -> str:
    # ... 初始化 ...

    # 创建任务计划
    plan = self.planner.create_plan(user_input)
    if plan and len(plan.steps) > 1:
        # 多步骤任务：持续执行模式
        return self._execute_plan(plan)
    else:
        # 单步骤任务：原有逻辑
        return self._single_step_run(user_input)

def _execute_plan(self, plan: TaskPlan) -> str:
    """持续执行任务计划的所有步骤"""
    results = []

    while plan.has_next_step():
        # 检查中断信号
        if self._check_interrupt():
            plan.set_status(TaskStatus.PAUSED)
            break

        # 获取下一步
        step = plan.get_next_step()
        step.status = TaskStatus.RUNNING
        self._notify_progress(plan)  # 通知 UI 更新

        try:
            # 执行单步
            result = self._execute_step(step)
            step.status = TaskStatus.COMPLETED
            step.result_summary = result
            results.append(result)

            # 记录经验教训
            if "error" in result.lower():
                self._record_lesson(step, result)

        except Exception as e:
            step.status = TaskStatus.FAILED
            step.error = str(e)

            # 尝试恢复：询问 LLM 是否可以继续
            if not self._can_recover_from_failure(plan, step):
                break

        # 通知 UI 更新
        self._notify_progress(plan)

    # 生成最终报告
    return self._generate_plan_report(plan, results)
```

#### 2.3 智能结束检测

当前问题在于 LLM 返回 `end_turn` 时无法区分：
- 情况 A：任务真正完成
- 情况 B：单步完成，还有后续步骤

解决方案：在系统提示中明确指导 LLM 使用 `continue_plan` 工具：

```python
SYSTEM_PROMPT_ADDITION = """
当您正在执行一个多步骤任务计划时：
- 完成一个步骤后，调用 continue_plan() 工具继续下一步
- 只有当所有步骤都完成时，才返回最终答案
- 如果遇到无法解决的问题，调用 pause_plan() 并说明原因
"""
```

新增工具：

```python
def continue_plan(result_summary: str = "") -> str:
    """继续执行任务计划的下一步"""
    # 设置标志，让主循环继续
    self.agent_loop.plan_should_continue = True
    self.agent_loop.current_step_result = result_summary
    return "继续执行下一步..."

def pause_plan(reason: str) -> str:
    """暂停任务计划执行"""
    self.agent_loop.plan_should_continue = False
    self.agent_loop.plan_pause_reason = reason
    return f"计划已暂停：{reason}"

def skip_current_step(reason: str = "") -> str:
    """跳过当前步骤"""
    if self.agent_loop.current_plan:
        self.agent_loop.current_plan.skip_current_step(reason)
    return "已跳过当前步骤"
```

#### 2.4 TaskTreeWidget 持久化

修改 `chat_panel.py`：

```python
def _run_agent(self, user_input: str):
    # 不在 finally 中清理任务树
    try:
        result = self.agent_loop.run(user_input)
        self._append_message("assistant", result)

        # 只有当计划真正完成时才清理
        if self.agent_loop.current_plan and
           self.agent_loop.current_plan.is_completed():
            QTimer.singleShot(3000, self.task_tree.clear_plan)

    except Exception as e:
        self._append_message("error", str(e))
```

#### 2.5 进度通知机制

```python
class ProgressNotifier:
    def __init__(self):
        self._callbacks = []

    def register(self, callback):
        self._callbacks.append(callback)

    def notify(self, plan: TaskPlan):
        for cb in self._callbacks:
            try:
                cb(plan)
            except Exception:
                pass  # UI 回调不应阻塞执行
```

---

## 功能三：QGIS 3.44 兼容性

### 问题描述

当前代码使用了 QGIS 3.x 高版本 API，无法在 QGIS 3.44（2021年发布）等旧版本上运行。

### 兼容性分析

| API | 当前版本 | 3.44 兼容 | 替代方案 |
|-----|---------|-----------|---------|
| `QgsProject.instance().mapLayers()` | 3.0+ | ✅ | - |
| `QgsProcessingFeatureSourceDefinition` | 3.0+ | ✅ | - |
| `QgsVectorLayer.selectedFeatures()` | 3.0+ | ✅ | - |
| `Qgis.MessageLevel` | 3.0+ | ✅ | - |
| `QgsApplication.processingRegistry()` | 3.0+ | ✅ | - |
| `QgsProcessingAlgorithm.createInstance()` | 3.0+ | ✅ | - |

### 需要修改的文件

#### 3.1 `tools/layer_tools.py`

```python
# 兼容性包装
def get_layer_by_name(name: str):
    """获取图层，兼容 QGIS 3.44+"""
    try:
        # QGIS 3.22+
        return QgsProject.instance().mapLayersByName(name)
    except AttributeError:
        # QGIS 3.44 兼容
        layers = QgsProject.instance().mapLayers().values()
        return [l for l in layers if l.name() == name]
```

#### 3.2 `tools/data_tools.py`

```python
# 确保使用旧版 API
def get_feature_count(layer_name: str) -> int:
    layer = iface.activeLayer()
    # 不使用 layer.featureCount()（某些版本有 bug）
    return len([f for f in layer.getFeatures()])
```

#### 3.3 版本检测与降级策略

```python
# qgis_agent.py 或 __init__.py
QGIS_VERSION = Qgis.versionInt()  # 例如 34400

def is_qgis_344_compatible():
    """检查是否需要启用兼容模式"""
    return QGIS_VERSION < 32200  # QGIS 3.22 LTS
```

### 测试矩阵

| QGIS 版本 | 测试状态 | 备注 |
|-----------|---------|------|
| 3.44.0 | 🔄 待测试 | 最低支持版本 |
| 3.22.0 | 🔄 待测试 | LTS 版本 |
| 3.28.0 | 🔄 待测试 | 当前主流 |
| 3.34.0 | 🔄 待测试 | 最新 LTS |

---

## 实施计划

### Phase 4.1：插件智能发现（预计 3-4 小时）

- [ ] 实现 `search_plugins()` 工具
- [ ] 实现 `install_plugin()` 工具
- [ ] 实现 `list_installed_plugins()` 工具
- [ ] 添加插件仓库 XML 解析器
- [ ] 集成到 AgentLoop

### Phase 4.2：任务计划持续执行（预计 4-5 小时）

- [ ] 修改 `AgentLoop.run()` 支持持续执行
- [ ] 实现 `continue_plan()` / `pause_plan()` 工具
- [ ] 修改 `TaskTreeWidget` 持久化逻辑
- [ ] 添加进度通知机制
- [ ] 更新系统提示词

### Phase 4.3：QGIS 3.44 兼容性（预计 2-3 小时）

- [ ] 审计所有 QGIS API 调用
- [ ] 添加版本检测逻辑
- [ ] 实现兼容性包装函数
- [ ] 编写兼容性测试

### Phase 4.4：测试与验证（预计 2 小时）

- [ ] 单元测试：插件搜索/安装
- [ ] 集成测试：多步骤任务执行
- [ ] 兼容性测试：QGIS 3.44 模拟环境
- [ ] 打包与发布

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 插件仓库 API 变更 | 中 | 高 | 多源备份，本地缓存 |
| LLM 不遵循 continue_plan 指令 | 高 | 中 | 强制轮询模式 + 超时重试 |
| QGIS 3.44 API 差异过大 | 低 | 高 | 优先支持 3.22+ |
| 任务计划死循环 | 中 | 中 | 最大步骤数限制 + 超时 |

---

## 成功标准

1. **插件管理**：能在 10 秒内搜索并安装指定插件
2. **任务持续执行**：5 步任务计划自动完成率 > 90%
3. **兼容性**：在 QGIS 3.44 上通过所有核心功能测试
4. **用户体验**：任务进度实时可见，支持中途干预