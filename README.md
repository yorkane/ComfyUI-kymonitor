# ComfyUI 提示执行监控节点 - 设计文档

## 1. 简介

### 1.1. 项目目标
开发一个 ComfyUI 自定义节点，用于实时监控 ComfyUI 提示（Prompt）的执行情况，并将关键信息通过多种渠道发送给用户，以便用户及时了解任务状态、进度和可能出现的错误。

### 1.2. 背景
ComfyUI 是一个强大的基于节点的图像生成界面。对于复杂或耗时的任务，用户往往需要一种机制来追踪任务的执行过程，而无需时刻关注界面。本自定义节点旨在满足这一需求，提供自动化的监控和通知功能。

## 2. 核心功能

### 2.1. 执行队列监控
-   **功能描述**: 定时从 `prompt_server.prompt_queue` 获取当前正在执行和等待执行的任务队列信息。
-   **数据源**: `prompt_server.prompt_queue.get_current_queue()`
-   **关键信息**: 任务ID, 节点状态, 进度, 开始时间等。

### 2.2. 历史记录访问
-   **功能描述**: 定时从 `prompt_server.prompt_queue` 获取已完成或已失败的任务历史记录。
-   **数据源**: `prompt_server.prompt_queue.get_history(max_items=max_items)`
-   **关键信息**: 任务ID, 节点状态, 结果, 开始时间, 结束时间, 错误信息（如有）, 错误堆栈（简略）。

### 2.3. 信息整合与摘要 (Info Object)
-   **功能描述**: 将从执行队列和历史记录中获取的信息进行整合与提炼，生成一个简短但包含所有关键状态的 `info` 对象。
-   **内容要求**:
    -   任务/队列状态（如：运行中、已完成、失败、排队中）
    -   当前执行节点信息（如：节点ID、节点类型）
    -   执行进度（百分比）
    -   任务开始时间
    -   任务结束时间（如果已完成或失败）
    -   执行结果（如：成功、失败）
    -   错误信息（如果发生错误）
    -   错误堆栈（限制层级，例如最多2层，避免信息过载）
-   **排除**: 完整的工作流定义信息，以保持信息的简洁性。

### 2.4. 通知发送
-   **功能描述**: 将生成的 `info` 对象通过预配置的渠道发送出去。
-   **支持渠道**:
    1.  **主要渠道**: 使用 ComfyUI 内置的 `prompt_server.send_sync(event_name, data)` 方法实时同步信息。
    2.  **可选渠道**:
        *   Redis: 将 `info` 信息发布到指定的 Redis Channel。
        *   RocketMQ: 将 `info` 信息发送到指定的 RocketMQ Topic。
-   **配置**: 用户应能配置启用哪些渠道以及各渠道的连接参数。

## 3. 模块设计

### 3.1. `query.py` - 信息处理模块

-   **职责**:
    -   调用 `prompt_server.prompt_queue.get_current_queue()` 获取当前队列信息。
    -   调用 `prompt_server.prompt_queue.get_history()` 获取历史执行信息。
    -   解析和处理原始数据。
    -   根据需求（2.3）构造简洁的 `info` 对象。
    -   处理错误信息和堆栈，确保其简短。
-   **输入**: 无（直接与 `prompt_server.prompt_queue` 交互）。
-   **输出**: `info` 对象列表（包含当前队列和历史记录的关键信息）。
-   **核心逻辑**:
    -   定义 `InfoBuilder` 类或相关函数。
    -   实现从原始队列数据中提取关键字段的逻辑。
    -   实现从原始历史数据中提取关键字段和错误信息的逻辑。
    -   格式化时间戳。
    -   截取和格式化错误堆栈。

### 3.2. `channel.py` - 通知渠道模块

-   **职责**:
    -   定义通知渠道的抽象接口（如果需要支持未来更多渠道）。
    -   实现各种通知渠道的初始化逻辑（连接建立、参数配置）。
    -   实现将 `info` 对象发送到各个已配置渠道的逻辑。
-   **支持的渠道实现**:
    -   `PromptServerChannel`:
        -   初始化: 无特殊要求。
        -   发送: 调用 `prompt_server.send_sync(event_name, info_data)`。`event_name` 可以是类似 `ky_monitor_update` 的自定义事件名。
    -   `RedisChannel`:
        -   初始化: 接收 Redis 服务器地址、端口、密码、Channel 名称等配置。
        -   发送: 使用 Redis 客户端库（如 `redis-py`）将 `info` 对象（通常序列化为 JSON 字符串）`PUBLISH` 到指定 Channel。
    -   `RocketMQChannel`:
        -   初始化: 接收 RocketMQ NameServer 地址、Topic 名称、Producer Group 等配置。
        -   发送: 使用 RocketMQ 客户端库将 `info` 对象（通常序列化为 JSON 字符串）发送到指定 Topic。
-   **配置管理**: 从外部配置文件或 ComfyUI 节点输入中读取渠道配置。

### 3.3. 主控模块 (例如 `__init__.py` 或 `monitor_node.py`)

-   **职责**:
    -   作为 ComfyUI 自定义节点入口，设计为在 ComfyUI 启动时自动加载并开始监控。
    -   从环境变量或 `config.json` 文件中读取配置，包括监控频率、`max_items` (历史记录)、启用的通知渠道及其参数。
    -   管理定时任务：按用户配置的频率，周期性执行监控逻辑。
    -   协调 `query.py` 和 `channel.py` 的工作流程：
        1.  调用 `query.py` 中的功能获取 `info` 对象。
        2.  将获取到的 `info` 对象传递给 `channel.py` 中已启用的渠道进行发送。
    -   处理节点生命周期，在 ComfyUI 启动时自动开始监控，并在 ComfyUI 关闭时（如果可能）优雅停止。
-   **与 ComfyUI 集成**:
    -   通过 ComfyUI 的插件机制自动加载。
    -   节点本身不提供可交互的输入参数界面；配置完全外部化。
    -   可能需要利用 ComfyUI 的 `server.py` 或 `execution.py` 中的某些上下文或实例（如 `prompt_server`）以及启动挂载点。

## 4. 数据结构

### 4.1. `info` 对象 (示例)
```json
{
  "id": "prompt_id_or_custom_id", // 任务唯一标识
  "type": "queue" | "history", // 区分是当前队列信息还是历史信息
  "status": "running" | "completed" | "failed" | "pending", // 任务状态
  "progress": 0.75, // 执行进度 (0.0 - 1.0), 仅当 running 时有效
  "current_node": { // 当前执行节点信息, 仅当 running 时有效
    "id": "node_id",
    "type": "KSampler"
  },
  "start_time": "YYYY-MM-DDTHH:mm:ssZ", // ISO 8601 格式
  "end_time": "YYYY-MM-DDTHH:mm:ssZ", // ISO 8601 格式, 仅当 completed 或 failed 时有效
  "result": "success" | "failure", // 仅当 completed 或 failed 时有效
  "error_info": { // 仅当 failed 时有效
    "message": "Error message content",
    "traceback": [
      "file1.py, line X, in function_A",
      "file2.py, line Y, in function_B"
    ]
  },
  "queue_position": 2 // 如果在队列中等待，表示其位置
}
```
*备注: 上述结构为示例，具体字段根据实际从 `get_current_queue()` 和 `get_history()` 返回的数据以及精简需求来确定。*

## 5. 配置

节点的配置通过环境变量或项目根目录下的 `config.json` 文件进行。如果两者都提供，可以约定一个优先级（例如，环境变量覆盖 `config.json` 的相应设置）。节点在启动时自动加载这些配置。

**可配置项示例**:

-   **监控频率**:
    -   环境变量: `KY_MONITOR_FREQUENCY_SECONDS` (例如: `5`)
    -   `config.json`: `{ "frequency_seconds": 5 }`
-   **历史记录最大条数 (`max_items`)**:
    -   环境变量: `KY_MONITOR_HISTORY_MAX_ITEMS` (例如: `100`)
    -   `config.json`: `{ "history_max_items": 100 }`
-   **`prompt_server.send_sync` 配置**:
    -   是否启用:
        -   环境变量: `KY_MONITOR_PROMPT_SERVER_ENABLED` (`true`/`false`)
        -   `config.json`: `{ "prompt_server_channel": { "enabled": true } }`
    -   事件名称 (`event_name`):
        -   环境变量: `KY_MONITOR_PROMPT_SERVER_EVENT_NAME` (例如: `ky_monitor_update`)
        -   `config.json`: `{ "prompt_server_channel": { "event_name": "ky_monitor_update" } }`
-   **Redis 渠道配置**:
    -   是否启用:
        -   环境变量: `KY_MONITOR_REDIS_ENABLED` (`true`/`false`)
        -   `config.json`: `{ "redis_channel": { "enabled": true } }`
    -   服务器地址 (host):
        -   环境变量: `KY_MONITOR_REDIS_HOST`
        -   `config.json`: `{ "redis_channel": { "host": "localhost" } }`
    -   端口 (port):
        -   环境变量: `KY_MONITOR_REDIS_PORT`
        -   `config.json`: `{ "redis_channel": { "port": 6379 } }`
    -   密码 (password, 可选):
        -   环境变量: `KY_MONITOR_REDIS_PASSWORD`
        -   `config.json`: `{ "redis_channel": { "password": "your_password" } }`
    -   数据库 (db, 可选):
        -   环境变量: `KY_MONITOR_REDIS_DB`
        -   `config.json`: `{ "redis_channel": { "db": 0 } }`
    -   发布频道名称 (channel_name):
        -   环境变量: `KY_MONITOR_REDIS_CHANNEL_NAME`
        -   `config.json`: `{ "redis_channel": { "channel_name": "comfyui_monitor" } }`
-   **RocketMQ 渠道配置**:
    -   是否启用:
        -   环境变量: `KY_MONITOR_ROCKETMQ_ENABLED` (`true`/`false`)
        -   `config.json`: `{ "rocketmq_channel": { "enabled": true } }`
    -   NameServer 地址 (namesrv_addr):
        -   环境变量: `KY_MONITOR_ROCKETMQ_NAMESRV_ADDR`
        -   `config.json`: `{ "rocketmq_channel": { "namesrv_addr": "localhost:9876" } }`
    -   Topic 名称 (topic):
        -   环境变量: `KY_MONITOR_ROCKETMQ_TOPIC`
        -   `config.json`: `{ "rocketmq_channel": { "topic": "comfyui_monitor_topic" } }`
    -   Producer Group (group_id, 可选):
        -   环境变量: `KY_MONITOR_ROCKETMQ_GROUP_ID`
        -   `config.json`: `{ "rocketmq_channel": { "group_id": "KY_MONITOR_PRODUCER_GROUP" } }`

配置信息由节点在启动时加载。

## 6. 错误处理

-   **节点内部错误**: 节点自身的逻辑错误（如配置错误、依赖缺失）应有明确的日志记录。由于没有UI界面，错误提示主要依赖日志输出。
-   **渠道发送错误**:
    -   连接失败：尝试重连（可配置次数/策略），记录错误日志。
    -   发送失败：记录错误日志。
    -   不应因为某个渠道发送失败而阻塞其他渠道或主监控逻辑。
-   **监控数据获取错误**: 如果从 `prompt_server.prompt_queue` 获取数据失败，应记录错误并跳过当次处理，等待下次重试。

## 7. 代码结构建议

```
ky_monitor/
├── __init__.py         # 注册节点, 主控逻辑一部分
├── monitor_node.py     # (可选) 节点核心类和主要逻辑
├── query.py            # 数据获取与 Info 对象构建
├── channel.py          # 通知渠道实现与管理
├── config.py           # (可选) 配置管理相关
└── README.md           # 本文档
```

## 8. 未来展望 (可选)

-   支持更多通知渠道（如 Email, Webhook, Slack, Telegram 等）。
-   提供更详细的节点级执行时间统计。
-   允许用户通过 `send_sync` 事件与监控节点进行双向通信（如：手动触发一次信息刷新）。
-   Web UI 展示监控信息。

---


(原始需求结束 不要覆盖)
# 原始需求
## 这是一个Comfyui 自定义节点，用于监控 ComfyUI prompt的执行情况
- 不要UI界面，通过环境变量或者 config.json文件进行配置。这个节点会被comfyui自动载入执行
- prompt_server.prompt_queue 的服务端代码在 doc/execution.py, 输出接口在 doc/server.py
- 定时执行 从 prompt_server.prompt_queue.get_current_queue() 获取执行队列 的情况(结果示例在doc/queue.json)
- prompt_server.prompt_queue.get_history(max_items=max_items)() 访问历史执行记录的情况(示例在doc/history.json)
- 将执行和历史结果拼在一起成为 info 发送至指定渠道(channal).
- info 信息需要简短，不用包含完整的工作流信息，保留关键的状态，节点信息，进度，开始时间，结束时间，结果，错误信息和错误堆栈(堆栈2层以内)
- 通知渠道首先使用 prompt_server.send_sync(event_name, data)方法，然后可以配置使用 redis 和rocketmq
- 要求代码尽量精简，分析信息构造info 放在query.py，渠道初始化和发送channel.py 做代码分离
(原始需求结束 不要覆盖)
