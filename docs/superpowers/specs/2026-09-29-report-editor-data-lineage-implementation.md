# Report Editor 数据追溯实施文档

## 1. 背景与目标

Report Editor 当前可以展示指标、图表和分析结论，但用户无法快速回答“这个数字从哪里来”“用了什么口径”“能否查看明细”。本项目为报告中的数字、图表和结论建立可追溯链路，使用户能够从报告内容回到指标定义、Profile、查询条件、数据快照和明细结果。

目标是：

- 点击报告中的指标或图表后，在编辑器内打开数据追溯面板。
- 展示指标定义、单位、来源字段、时间窗口、筛选条件、计算公式和生成时间。
- 支持按 Profile 已声明的维度下钻到明细摘要。
- 追溯信息绑定报告 revision、Profile revision 和数据快照，保证历史报告可复现。
- PDF 和 Word 保留来源编号与脚注，在线编辑器提供完整明细。

## 2. 范围

### 首期范围

首期只覆盖报告运行时已经产生的结构化指标和图表：

- `metricCode` 已存在于 Reporting Profile。
- 查询使用已有的 `queryWindow`、`sourceRefs`、维度和筛选条件。
- 报告 Markdown 中的指标块、图表块可以关联 `traceId`。
- 追溯面板展示元数据和结果摘要。
- 明细下钻最多选择一个 Profile 维度，并复用已有数据查询能力。

### 暂不纳入首期

- 任意 SQL 编辑器。
- 用户自定义计算字段。
- 跨 Profile 的指标比较。
- 对 PDF/Word 内的交互式明细下钻。
- 对历史报告重新查询当前数据来“补生成”追溯记录。

## 3. 用户流程

1. 用户打开报告编辑器。
2. 指标、表格单元格和图表显示来源标记，例如 `①`。
3. 用户点击来源标记、指标或图表数据点。
4. 右侧追溯面板打开，显示当前对象的指标定义、来源、口径、筛选条件和摘要值。
5. 用户选择一个允许的维度，例如“院区”或“月份”。
6. 系统返回按该维度分组的明细摘要，并保留原始追溯上下文。
7. 用户可以复制追溯信息或打开对应数据表视图。

## 4. 推荐架构

采用“报告内容引用 TraceRecord，TraceRecord 引用不可变查询快照”的结构。

```text
Report revision
  └─ content block / chart point
       └─ traceId
            └─ TraceRecord
                 ├─ metric definition
                 ├─ Profile revision
                 ├─ sourceRefs
                 ├─ query window and filters
                 ├─ formula
                 ├─ result summary
                 └─ snapshot identity
```

追溯记录在报告生成和验收阶段创建，之后只读。重新生成报告会创建新的 revision 和新的 TraceRecord，不修改旧记录。

## 5. 数据模型

建议新增 `ReportTraceRecord`，字段如下：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `traceId` | string | 追溯记录稳定 ID |
| `reportId` | string | 报告 ID |
| `revision` | integer | 报告 revision |
| `blockId` | string | 正文、表格或图表块 ID |
| `metricCode` | string | Profile 中的指标代码 |
| `label` | string | 展示名称 |
| `value` | number/string | 结果值 |
| `unit` | string | 单位 |
| `profileId` | string | 生效 Profile ID |
| `profileRevision` | string | Profile revision |
| `effectiveProfileHash` | string | 生效 Profile 哈希 |
| `sourceRefs` | array | 数据源、表和字段引用 |
| `queryWindow` | object | current、yoy、mom 期间窗口 |
| `filters` | object | 强制范围和本次查询筛选条件 |
| `dimensions` | array | 可下钻维度及其字段引用 |
| `formula` | object/null | 同比、环比、占比等计算说明 |
| `resultSummary` | object | 行数、合计、最小值、最大值等摘要 |
| `snapshotId` | string | 数据快照或查询结果身份 |
| `generatedAt` | datetime | 生成时间 |
| `sourceSha256` | string | 追溯载荷哈希 |

`TraceRecord` 不保存数据库密码、DSN 或原始敏感连接信息。明细结果只通过服务端授权接口读取。

## 6. 报告内容关联

报告生成器需要为以下对象写入追溯引用：

- 指标卡：`traceId` 放在指标对象上。
- Markdown 中的事实数字：使用受控标记，例如 `<!-- trace:trace-id -->`，不允许模型自由构造 ID。
- 图表：图表级引用和系列/数据点引用分开保存。
- 表格：表格级引用以及单元格对应的 `traceId`。
- 自然语言结论：首期只允许引用生成器提供的指标证据，不能从自由文本中反推追溯关系。

协议层必须校验：

- `traceId` 属于当前 report revision。
- `metricCode` 存在于当前生效 Profile。
- `sourceRefs` 与实际查询快照一致。
- 追溯引用不存在时显示软告警，并记录日志；不因单个引用缺失阻断整份报告。

## 7. API 设计

### 获取追溯记录

```http
GET /reports/v1/editor/{report_id}/{revision}/api/traces/{trace_id}
```

响应返回脱敏后的 `TraceRecord`，包含指标定义、来源字段、查询窗口、筛选条件和结果摘要。

### 查询下钻结果

```http
POST /reports/v1/editor/{report_id}/{revision}/api/traces/{trace_id}/drilldown
```

请求：

```json
{
  "dimension": "area",
  "limit": 100,
  "cursor": null
}
```

服务端只接受当前 `TraceRecord.dimensions` 中声明的维度，并自动继承原始查询的 Profile 强制范围、期间窗口和筛选条件。

响应包含：

- 维度名称和展示标签。
- 分组值、指标值和必要的比较值。
- 下一页游标。
- 实际执行的查询快照 ID。

### 读取图表追溯

图表接口复用同一 `TraceRecord`，数据点只传递 `traceId` 和点位索引，服务端根据已登记的查询结果定位数据，避免前端提交任意 SQL 或任意字段。

## 8. 前端交互

新增 `TracePanel`，职责保持单一：读取追溯记录、展示来源、发起下钻和复制摘要。

面板分为四个区域：

1. **指标概览**：名称、当前值、单位、期间。
2. **计算口径**：定义、公式、同比/环比规则。
3. **数据来源**：Profile、数据表、字段、生成时间和快照 ID。
4. **明细下钻**：允许的维度按钮、结果表格和分页。

加载失败、记录过期或明细不可用时显示软告警，保留报告正文可编辑能力。追溯面板不阻塞保存和导出。

## 9. 后端实现拆分

### 9.1 追溯登记

在报告运行时生成结构化指标后，由报告工具统一登记 `TraceRecord`。登记动作必须和报告 revision 的产物登记使用同一个 revision 身份。

### 9.2 持久化

首期可将追溯记录作为 revision 附属 JSON 存储在现有报告工作区和状态仓库中；当查询量和保留周期扩大后，再迁移到独立的追溯表。无论存储方式如何，外部 API 保持不变。

### 9.3 下钻执行

下钻请求只接收 `traceId` 和已声明维度。服务端从 TraceRecord 恢复查询上下文，再调用现有数据源适配器生成受限查询。查询必须复用 Profile 的 `scopeFilters`，用户请求不能覆盖这些范围。

### 9.4 权限

每次读取追溯记录或下钻都校验：用户、公司、会话、报告 ID、revision 和下载/编辑授权。TraceRecord 不得跨报告或跨用户读取。

## 10. PDF 和 Word

在线编辑器使用完整追溯面板；PDF 和 Word 使用脚注方式表达：

- 指标或图表旁显示来源编号。
- 文档末尾增加“数据来源与口径”章节。
- 每条脚注包含指标名称、期间、Profile revision、主要来源表和生成时间。
- 不把数据库连接信息、完整 SQL 或明细敏感数据写入文档。

首期不要求导出文档可交互下钻，但导出的来源编号必须能在在线编辑器中定位到对应 `traceId`。

## 11. 测试计划

### 单元测试

- TraceRecord 严格校验和哈希稳定性。
- Profile 指标、维度和 sourceRefs 一致性校验。
- 强制范围不能被下钻请求覆盖。
- 脱敏逻辑不泄露连接信息。
- 旧 revision 的 TraceRecord 不被新 revision 覆盖。

### API 测试

- 合法追溯读取返回 200。
- 跨用户、跨报告、跨 revision 返回 403/404。
- 未声明维度下钻返回软错误。
- 游标分页和空结果处理。
- 过期快照返回可识别错误码。

### 前端测试

- 点击指标打开追溯面板。
- 追溯记录加载失败不影响编辑。
- 下钻维度切换和分页。
- 图表数据点映射到正确 traceId。
- 追溯信息复制和关闭行为。

### 回归测试

- 报告生成、编辑保存、PDF/Word 导出仍然成功。
- 有追溯和无追溯的报告都能导出。
- 多个 custom/function 工具调用的既有协议回归不受影响。

## 12. 分阶段实施

### Phase 1：来源面板 MVP

- 定义 TraceRecord。
- 在指标和图表产物中写入 traceId。
- 增加读取接口和前端追溯面板。
- PDF/Word 增加来源脚注。

验收：用户点击报告中的指标，能看到定义、来源字段、期间、筛选条件和生成时间。

### Phase 2：单维度下钻

- 增加允许维度声明。
- 增加受限下钻接口。
- 增加明细摘要和分页。

验收：用户可以从总收入下钻到院区或月份，并且结果继承原始 Profile 范围。

### Phase 3：结论证据链

- 将自然语言结论与多个 TraceRecord 关联。
- 面板显示结论的指标证据和计算关系。
- 支持结论级来源编号。

验收：用户可以从“收入下降主要来自某院区”定位到支撑该判断的指标和查询快照。

## 13. 上线与观测

- 使用 feature flag 控制追溯标记和追溯面板。
- 首期只对内部用户开启。
- 记录追溯读取成功率、下钻成功率、平均耗时、空结果率和脱敏错误。
- 数据查询超时只影响追溯面板，不影响报告阅读和编辑。
- 保留旧报告的 TraceRecord，按照报告 revision 的保留策略清理。

## 14. 完成标准

- 报告中的指标、图表和表格可以稳定关联 TraceRecord。
- 追溯接口不会接受任意 SQL、任意字段或未声明维度。
- 追溯结果与报告 revision、Profile revision 和查询快照一致。
- 旧报告能够继续读取原始追溯信息。
- PDF 和 Word 具有可定位到在线追溯记录的来源编号。
- 追溯功能异常不会阻断编辑、保存和导出主流程。
