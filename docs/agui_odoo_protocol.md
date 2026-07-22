# AG-UI / HRP 协议

版本：`agui.odoo.v2`

本模块将一个聊天运行时接入当前原生 HRP 的
`BasicModel` / `Controller` / `Renderer`。React 不渲染或持久化第二份 HRP 表单模型。

## 版本握手

挂载 React 之前，HRP `/agui_chat/config`、已加载的资源包和配置的 AgentOS 协议端点必须一致：

```json
{
  "protocol": "agui.odoo.v2",
  "module_version": "12.0.8.8.9",
  "bundle_version": "12.0.8.8.9",
  "command_catalog_hash": "sha256"
}
```

AgentOS 在由配置的 `/agui` 运行时 URL 推导出的 `/config` 地址公开
`protocol`、`bundle_version` 和 `command_catalog_hash`。声明缺失或不一致时禁用聊天和宿主工具，
但不会阻止 HRP WebClient 启动。

## 状态归属

每个 `RunAgentInput.state` 必须严格使用以下外层结构：

```json
{
  "protocol": "agui.odoo.v2",
  "host": {
    "snapshotId": "agui-...",
    "hostRevision": 8,
    "interactive": true,
    "surface": "dock",
    "controller": {}
  },
  "agent": {}
}
```

* `host` 只能由 HRP `agui_host` 快照投影得到。浏览器 `HostBridge` 保留完整本地快照，
  AgentOS 只接收面向模型的投影，不维护第二份业务状态。
* `STATE_SNAPSHOT`、`STATE_DELTA` 和 JSON Patch 事件只能写入 `agent`；尝试修改 `/host` 时忽略并报告。
* `hostRevision` 是浏览器页面版本，`sessionRevision` 是数据库会话版本，二者不比较，也不相互恢复。
* 可见菜单目录是独立的宿主快照，不写入 `RunAgentInput.state`，也不计入页面快照预算；仅目录变化不会增加
  `hostRevision`。浏览器从原生 `WebClient.menu_data` 派生目录，只接受自身 action 为有效
  `ir.actions.act_window` 或 `ir.actions.client` 的叶节点。含子节点的节点永远不可导航，即使 Odoo
  WebClient 将后代 action 复制到了该节点。
* 会话恢复只加载消息、`agentState` 和界面偏好，不恢复 `hostState`。

List/Kanban 投影中的 `selection` 只包含 `model`、宿主选择的 `scope` 和 `selectedCount`。
窗口 action 与选择范围的 domain/context、选中 ID、可见行候选及行绑定控件标签留在浏览器中。
字段元数据、聚合视图能力和精确的 `viewTarget` 保持可用。表单快照保留现有记录和控件语义。

快照保留最终原生视图中每个字段的元数据，包括 binary 和不支持的 widget 字段；binary 值始终省略，
敏感值始终脱敏。`capabilities.x2many` 直接从完整 Form `fieldsInfo` 发现每个 one2many，导出 schema
来源、schema 哈希/数量、集合数量、操作状态、字段 token 和轻量已加载行 token，不包含子记录值或重复的子字段映射。

快照预算为 256 KiB。必要时宿主依次删除非 dirty 记录值、one2many 值和非必要的行显示文本。
不会删除字段元数据、dirty 值或必需的操作 token。如果剩余元数据和必需状态仍超出预算，宿主返回
`snapshot_too_large`，不会静默丢弃字段。

## 客户端工具

HRP 在当前 `RunAgentInput.tools` 中发布标准 AG-UI 客户端工具 schema：

- `odoo.navigate_menu`
- `odoo.apply_filter`
- `odoo.apply_group`
- `odoo.export_current_view`
- `odoo.open_record`
- `odoo.open_create`
- `odoo.switch_view`
- `odoo.open_x2many_record`
- `odoo.open_x2many_create`
- `odoo.enter_edit_mode`
- `odoo.activate_view_control`
- `odoo.search_relation`
- `odoo.stage_current_form`
- `odoo.patch_current_form`
- `odoo.validate_current_form`
- `odoo.save_current_form`
- `odoo.discard_current_form`

React 只执行本次运行声明了完全相同名称的工具。Agno 服务端工具在收到
`TOOL_CALL_RESULT` 前仅用于展示。

`odoo.export_current_view` 仅接受当前 List `viewTarget` 和 `format: "xlsx"`。
浏览器从最新 `ListController` 与 `BasicModel` 派生导出范围：有具体勾选时导出这些 ID，
无勾选时使用当前 domain；原生“全选筛选结果”继续使用 `getActiveDomain()`。当前列表存在
未保存编辑时拒绝导出。字段严格按 `renderer.columns` 顺序生成，并排除按钮、binary、不可见列、
敏感配置字段和敏感命名字段，不隐式加入 External ID。服务端授权会再次校验模型、字段类型与策略白名单。

该工具始终要求用户确认。`preview.export` 只公开 `workspacePath`、`format`、`scope`、
`recordCount`、`fieldCount` 和有序列标签。确认后浏览器使用当前 Odoo 会话调用
业务 `/web/export/xlsx`，请求字段与 `dy_base.DataExport.direct_export_data()` 一致，包含列表
`fieldInfo`、分组布局、当前 action 对象、分组排序、明细排序以及 `context.export_way/expWay`；随后携带当前
thread capability 调用 AgentOS
`POST /workspace/files`。成功结果包含 `path`、`filename`、`format`、`size`、`recordCount` 与
`fieldCount`，其中 `filename` 由 Odoo `web.contentdisposition` 解析响应头得到。该文件名仅作为
multipart 文件元数据；实际写入位置仍是确认时绑定的 `path`。domain、ID、context、字段描述符、
capability 和文件内容不会进入授权、审计或消息。

导出路径固定为 `exports/<model>-<capturedAt UTC>-<tool call 短 ID>.<format>`，因此同一绑定快照
的重复 prepare 路径不变。单文件最多 10 MiB；空结果允许生成仅含表头的文件。分组、排序、
字段精度和 `expWay` 语义由业务 XLSX 导出控制器处理。稳定失败码包括
`no_current_list`、`unsaved_changes`、`export_no_fields`、
`odoo_export_failed`、`export_file_too_large`、`workspace_capability_rejected`、
`workspace_path_conflict` 和 `workspace_upload_failed`，并保留现有 stale/target 错误。

AgentOS `/config.limits.workspace_file_bytes` 固定为 `10485760`。`POST /workspace/files` 是
multipart create-only 接口，成功返回 `201 {ok, entry}`；同一 thread/path 通过 PostgreSQL
advisory lock 串行化存在性检查与上传，重名返回 `409 workspace_path_conflict`。既有
`POST /workspace/upload` 仍保留覆盖语义。

`odoo.navigate_menu` 使用专用菜单目标，其中还包含 `catalogId` 和 `catalogRevision`。
绑定当前视图的命令携带包含 `controllerId`、`dataPointId`、`model` 和 `resId` 的完整目标。
目标成员缺失或过期时失败关闭。存在菜单目录标识时，服务端幂等绑定也包含该标识。

每个原生快照都公开 `capabilities.viewTypes`，其值仅限当前窗口 action 声明的 `kanban`、`list`
和 `form`。Odoo action 或视图声明中的 `tree` 会在宿主边界统一归一化为协议值 `list`，二者兼容，
但快照和工具参数始终使用 `list`。`odoo.switch_view` 仅允许从当前 `viewType` 为 `list` 或 `kanban` 的页面发起，
目标值仍须是其中一个当前值，并等待新的交互快照后才报告成功；当前为 `form` 时拒绝调用。
dirty 表单、当前活动视图和不可用目标会被拒绝。从 List/Kanban 切换到 Form 会进入未保存的新建表单，
因此还要求 action 具备 create 能力；打开已有记录仍须使用 `odoo.open_record`。

List/Kanban 快照将原生分组公开为宿主持有的能力：

```json
{
  "group": true,
  "groupFields": {
    "document_type": {
      "name": "document_type",
      "string": "单据类型",
      "type": "selection",
      "intervals": []
    },
    "document_date": {
      "name": "document_date",
      "string": "单据日期",
      "type": "date",
      "intervals": ["day", "week", "month", "quarter", "year"]
    }
  },
  "groupBy": [{"field": "document_date", "interval": "month"}]
}
```

`groupFields` 只包含原生 SearchView“分组依据”菜单公开的可排序、非敏感字段。支持类型为
`many2one`、`char`、`boolean`、`selection`、`date` 和 `datetime`。Form 视图及禁用分组的视图
返回 `group: false`、空字段映射和空当前状态。

`odoo.apply_filter` 和 `odoo.apply_group` 仅当最新宿主快照的 `viewType` 为 `list` 或 `kanban`
时可调用；Odoo `tree` 视图按规范值 `list` 兼容，`form` 及其他视图类型禁止调用。
`odoo.apply_group` 接受精确的当前 `viewTarget`
和必填的 `groupBy` 数组，最多三项。
每项必须包含 `field`；date 和 datetime 项还可提供 `interval`，取值为 `day`、`week`、`month`、
`quarter` 或 `year`，默认 `month`。数组按给定顺序替换完整的当前分组；`[]` 清空分组，
它不是增量添加或删除操作。

该页面命令使用以下完整 JSON Schema 声明：

```json
{
  "name": "odoo.apply_group",
  "parameters": {
    "type": "object",
    "additionalProperties": false,
    "required": ["target", "groupBy"],
    "properties": {
      "target": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "snapshotId",
          "hostRevision",
          "controllerId",
          "dataPointId",
          "model",
          "resId"
        ],
        "properties": {
          "snapshotId": {"type": "string"},
          "hostRevision": {"type": "integer"},
          "controllerId": {"type": "string"},
          "dataPointId": {"type": ["string", "boolean"]},
          "model": {"type": ["string", "boolean"]},
          "resId": {"type": ["integer", "boolean"]}
        }
      },
      "groupBy": {
        "type": "array",
        "maxItems": 3,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": ["field"],
          "properties": {
            "field": {
              "type": "string",
              "minLength": 1,
              "maxLength": 128
            },
            "interval": {
              "type": "string",
              "enum": ["day", "week", "month", "quarter", "year"]
            }
          }
        }
      }
    }
  }
}
```

宿主只移除 `groupByCategory` facet，复用或创建原生 `Filter`/`FilterGroup` 映射和菜单项，
更新日期 interval，并触发一次查询重置。其他筛选 facet、domain、排序和 context 均保留。
活动收藏保留其 domain、排序和其他 context，但会移除自身的 `group_by`，避免覆盖请求的分组。
宿主绝不直接写入 `BasicModel.groupedBy`。

该命令是 read 级页面命令，不属于 `WRITE_COMMANDS`，无需写确认。稳定分组错误码为
`group_unavailable`、`invalid_group_by`、`invalid_group_field` 和
`invalid_group_interval`。成功结果返回 `applied: true`、规范化后的有效 `groupBy`，以及刷新的
`snapshotId` 和 `hostRevision`。

只有声明了 `odoo.navigate_menu` 时，才允许不经显式 `@` 选择进行导航。除当前 `menuTarget` 外，
工具只接受两种输入形式之一：`{query}` 或 `{menuId, actionId}`。混合形式或不完整的 ID 对返回
`invalid_menu_navigation`。

对于 `{query}`，宿主规范化包裹符、空白、分隔符和大小写，优先精确匹配完整路径或叶节点名称，
仅在没有精确结果时使用包含匹配。结果包含 `matchType`、`matchCount`、`truncated`、目录元数据及最多
八个候选。未截断的唯一结果在同一次工具调用中打开；无结果或多个候选时返回
`navigated: false`，且不打开任何菜单。

紧随其后的“第一个”至“第八个”序号回复（包括阿拉伯数字和可选的“选择”）只有在候选项仍具有相同的
menu/action ID，且搜索结果的目录 ID 和版本未变化时，才转为显式菜单选择。随后 React 只为首个页面动作
公开 `odoo.navigate_menu`，并向宿主提供所选 `menuId` 和 `actionId`。缺失、越界、过期或已完成的选择
仍作为普通对话输入，绝不授权导航。

对于明确的“打开”“进入”“导航到”或“跳转到”请求，如果目标精确匹配可见叶节点名称或完整路径，React
会添加不含 menu/action ID 的 `HRP 菜单导航请求`。该上下文要求使用原始 query 调用一次
`odoo.navigate_menu`。AgentOS 强制选择该工具；纯文本或不同的首个可执行事件会以
`required_tool_violation` 拒绝。问题、未知目标、歧义结果、过期目录和已完成的打开操作不会获得该强制导航上下文。

首次运行不发送完整可见目录。只有同一目录返回 `matchType=none` 后，紧随其后的客户端工具续跑才接收
`当前用户可见 HRP 菜单`。该上下文只包含目录元数据、完整性和原始 `fullPath` 字符串，绝不包含
menu/action ID。UTF-8 预算为 128 KiB，路径不截断。若 `complete=false`，禁止语义改写，用户必须通过
`@` 选择。目录完整时，智能体最多可通过 `odoo.navigate_menu` 重试两个原始路径。

对于 `{menuId, actionId}`，只有终端菜单存在于当前可见目录、action 未变化且页面与目录目标均为最新时，
宿主才接受该 ID 对。ID 对只能来自当前候选上下文；宿主不要求同一次运行中先执行搜索。目录变化返回
`stale_menu_catalog`，action 变化返回 `menu_action_conflict`，菜单缺失返回 `menu_unavailable`。

## 表单命令

以下命令仅能在最新宿主快照的 `viewType=form` 时调用；List/Kanban 页面必须先进入真实表单，其他视图类型会被宿主拒绝：
`odoo.search_relation`、`odoo.stage_current_form`、`odoo.patch_current_form`、`odoo.validate_current_form`、
`odoo.save_current_form` 和 `odoo.discard_current_form`。

关系搜索规则：

* `odoo.search_relation` 只接受当前原生表单中的字段，支持可写的 many2one/many2many 字段。
  已加载的 one2many 行由当前 `rowToken` 绑定；关系字段名仍使用该行快照中的子字段名。
* 新行必须先通过可见的原生新建控件创建。暂存带已发放 row token 的标量依赖后，关系搜索会基于实时子数据点及其 onchange 状态计算。
* 浏览器针对实时 BasicModel 数据点（包括未保存 onchange/dirty 状态）计算
  `record.getDomain({fieldName})` 和 `record.getContext({fieldName})`，再以当前 HRP 用户调用 `name_search`。
* 绝不接受或返回原始 domain/context 值给智能体。
* 唯一精确候选可直接使用；多个候选必须由用户明确选择，智能体不得猜测 ID。
* 应用 patch 前会再次依据最新 domain 检查关系 ID；many2many unlink 仅限当前已选 ID。

暂存规则：

* `odoo.stage_current_form` 与 patch 使用相同的可见/可写字段校验、原生 `_applyChanges`、关系 domain 复查和 onchange 完成流程，但绝不调用 `saveRecord()`。
* 每次成功暂存都会发布新快照；后续关系搜索、校验和保存必须使用该快照，不得使用过期 token。

Patch 规则：

* 字段必须存在于 `fieldsInfo.form` 且当前可见、可写。
* 已有 dirty 字段会冲突，不允许部分应用。
* 标量使用 HRP 字段解析器；many2one 接受显式整数 ID、HRP 风格的 `[ID, displayName]` 对，或快照风格的 `{id, displayName}` 对象。
* many2many 只支持对已有 ID 执行 `link`、`unlink` 和 `replace`。
* 一个 patch 中 one2many 的 `create`、`update`、`delete` 总操作数最多 40。除非完整子 schema 已加载，否则父表单批量操作以 `requires_form_activation` 拒绝。普通新建/打开/编辑使用 `odoo.open_x2many_create` 和 `odoo.open_x2many_record`。
* 含 one2many 的 patch 使用原生 BasicModel 的 `CREATE`、`UPDATE` 和 `DELETE`。patch 只保存一次父记录；stage 保持父记录 dirty，等待后续显式校验/保存。没有通用 RPC 回退。

Patch 策略公开 `confirmation_mode`：`risk`（默认）、`always`、`never`，以及可选的高风险字段白名单。
在 `risk` 模式下，由服务端而非智能体为多字段 patch、many2one 或 many2many/one2many 字段及策略标记字段要求确认。
高风险 prepare 必须包含由实时 BasicModel 生成的预览。每个预览变更包含字段名和标签、字段类型、旧值、新值及风险原因；敏感值只显示为 `[redacted]`。

预览和授权绑定当前 controller、记录、快照及 `hostRevision`。批准前绑定变化时拒绝旧授权，并要求新预览和新确认。
仅当同一记录的快照过期时，低风险 patch 才可刷新并重新绑定一次。dirty 字段冲突、ACL 失败、校验错误、onchange 失败和保存失败绝不自动重试。

## 浏览器授权

`/agui_chat/host_command` 是唯一的浏览器命令策略端点。其 prepare/confirm/complete 阶段将精确命令 payload 绑定到用户、公司、run、thread 和工具调用 ID。
重放幂等键返回已存结果或以进行中失败；payload 变化会被拒绝。

确认批准或拒绝会在 React 启动唯一一次后续 Agent 运行前持久化。重复确认事件会被忽略或重放已存结果，不能重复执行命令或恢复 Agent。

成功且符合条件的 patch 获得一次性 undo 授权，十分钟后过期。Undo 是内部宿主操作，不发布到 Agent 工具目录。
它支持现有标量、many2one 和 many2many patch 形式；敏感、binary 和 one2many 字段不生成 undo 授权。
应用逆 patch 前，宿主要求当前记录相同、无相关 dirty 字段，且当前值仍等于原 patch 写入的值；否则返回 `undo_conflict`，不覆盖更新数据。
Undo 执行及其失败结果会被存储以便幂等重放。

动作模拟、通用 RPC/CRUD 和任意模型方法不属于本协议。

## 业务命令

同步服务端命令使用 `odoo.business.<domain>.<verb>` 下的精确名称。只有同时存在于 Python 注册表和
`enabled_business_commands` 中的命令，才会作为当前运行的客户端工具发布；注册的 JSON schema 即工具的 `parameters`。

注册命令默认访问级别为 `write`。显式注册为 `read` 的命令在关闭 `write_tools_enabled` 时仍可发布和执行。
两种访问级别都要求精确匹配策略。绑定解析器可绑定当前消息的不透明 token 并按模型生成策略输入；执行时会再次运行，
因此 token 可见性、ACL、记录规则、公司、浏览器会话、过期或策略撤销失败都会使整批操作原子失败。

浏览器调用 `/agui_chat/business/prepare`，必要时复用普通确认界面，再使用服务端绑定的 payload 和授权 token
调用 `/agui_chat/business/execute`。业务命令要求精确工具策略，缺少策略时失败关闭。各插件负责自身模型 ACL、
记录规则、状态和 domain 检查。执行器还应用服务端 schema 校验、用户/公司/run/tool-call payload 绑定、授权过期、
幂等锁、数据库 savepoint、已存结果重放、默认敏感键脱敏和脱敏审计。不存在通用业务 handler、RPC、CRUD 或任意模型方法回退。

`DELETE /workspace/file` 只接受 `threadId`、`path` 和可选 JSON 布尔值 `recursive`；字符串或数字形式的伪布尔值及未知字段会被拒绝。
工作区下载同时发送 ASCII `filename` 回退和 RFC 5987 `filename*=UTF-8''...`，使非 ASCII 文件名有效，
且不会把 Unicode 直接写入 Latin-1 响应头。

## 会话与界面

会话 JSON 端点仍位于 `/agui_chat/session/*`。payload 字段为 `messages`、`agentState`、`uiPreferences` 和 `sessionRevision`。

`POST /agui` 使用增量运行消息。普通运行只发送最新用户消息。客户端工具续跑只发送连续尾部的 `tool` 结果消息，保持原始顺序。
每次请求仍完整发送工具声明、当前页面上下文和状态外层结构。独立菜单路径目录只在上文所述的无结果续跑中发送。
AgentOS PostgreSQL 是对话历史权威，并加载最近 10 次运行。HRP `session/save` 继续持久化完整 UI 消息快照，用于恢复和版本合并。

每条最终 assistant 消息都在 `extra_data.agent_run_id` 保存 AgentOS run ID。同一轮的所有客户端工具续跑复用该 ID。
普通运行的 `forwardedProps` 为空；分支运行只允许 `branch.sourceThreadId`、`branch.sourceRunId` 和 `branch.targetMessageId`。
身份信息和任意后端参数绝不通过该字段转发。

`session/fork` 锁定并刷新源会话，创建名为 `原名称（分支）` 的新会话，记录 `parent_session_id`，只复制选定最终答案之前的消息。
引用的 HRP 附件会复制到新会话并重写其 ID。分支继承 UI 偏好、agent 状态、界面和智能体选择，但获得新的 `thread_id`。

AgentOS 校验源、目标 thread 的 capability，并要求数据库、用户、公司和浏览器会话身份一致。
它只复制截至选定 run 的源运行，为每个复制 run 分配新 ID，发出旧到新的映射，并使用
`regenerate=true`、`replace_original=true` 调用 Agno 重新生成。选定 run 已完成的工具交互保留在历史中，不会再次执行；源会话不会修改。

分支工作区复制源会话的当前文件，而不是选定 run 时的历史快照。创建目标沙箱前校验清单：最多 2000 个普通文件、总计 256 MiB、单文件 25 MiB。
符号链接、非普通文件、无效路径和任一超限都会拒绝整个工作区。`RUN_STARTED` 前失败会删除已准备的 AgentOS/工作区状态；React 归档 HRP 分支并停留在源会话。
`RUN_STARTED` 后的模型错误在分支中可见。Agent 会话持久化及分支工作区复制/回滚使用原生异步 PostgreSQL 和 Daytona 客户端，因此分支准备不会阻塞 AG-UI SSE 事件循环。
受控分支失败在 `RUN_ERROR.code` 发出稳定的 `branch_*` 值；意外失败使用 `branch_failed`。客户端消息不包含后端原始异常文本。

每次保存都提供 `expectedSessionRevision`。首次版本冲突时，React 重载会话，按消息 ID 合并本地和远程消息，并重试一次。
第二次冲突保留内存消息和确认结果并报告明确错误，绝不静默丢弃。

界面只存在 `dock` 和 `standalone`。`standalone` 是 WebClient 内可移动、可调整大小的浮动窗口；协议值为兼容既有会话而保留。
切换界面只移动唯一稳定的 React 宿主节点，不卸载节点、不重载会话，也不取消活动 SSE 运行。

升级到 `12.0.8.8.0` 会归档此前所有活动 HRP 聊天会话，并将其工作区加入既有清理 worker。
HRP 和 AgentOS 审计数据保留，但不会再次使用旧 thread。升级后的首次聊天会自动创建支持 run ID 的新会话。
