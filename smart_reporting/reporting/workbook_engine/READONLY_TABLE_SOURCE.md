# 只读表格删除身份

2026-11-10。固定源 `/home/junge/pros/genoffice-source-full` HEAD
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。
来源为 `packages/xlsx-gateway/src/gateway/xlsx-sheets.ts` 的根表名称提取、
`xlsx-gateway.ts` 的最终删除集合与共享 incoming 保留，以及
`xlsx-table-edit.ts` 的 name/displayName 别名提取。
这是本地 namespace/完整性加强适配，不是上游源码逐字复制。

`SheetModel.tableSources` 完整保存真实 worksheet/tablePart/relationship 所属
的 `{path,name,displayName}`；空数组表示已核对无表，缺字段表示身份未核对。
`tableSourcesReadOnlyReason` 表示身份不完整，不发布部分列表。
所有根身份核对完成后才进行编辑投影，因此列、范围、样式投影失败只影响
`tables` 和 `tablesReadOnlyReason`，不会丢失另一张表的删除身份。

独立读取器用 saxes 检查完整 XML、根 namespace、根属性以及所有所属关系。
name/displayName 至少存在一个且非空，另一字段可回退；name-only 仍无法
进入现有可编辑投影。不同表的任一别名碰撞均判身份不完整。
不扫描 ZIP 认领 orphan table，也不信任外来 namespace、重复关系 ID、
外部关系、越界路径、重复目标或缺失部件。

保存端复用同一根身份读取，检查两个别名且缺身份拒绝结构删除。
除兼容常规 table 路径外，真实 table 类型关系识别非标准 part 路径；
只有最终 removedParts 内的表才参与依赖检查，共享目标由原 planner 保留。
语义仍是固定源大小写不敏感 TableName[ token，不宣称完整公式解析。
前端集成与 bundle 由主任务负责，本文件不宣称浏览器验收完成。

验证：新增 table-source.test.ts 首轮 8 个预期断言失败后转绿；
非标准路径新增用例先失败再修复。新增共 11 个用例，含两表投影失败、
缺名/外来根/畸形 XML/别名冲突、外来关系 namespace、保存别名、非标准路径、
共享 incoming 与 name-only；table-read 22 项定向通过。
owned-table-delete-dependencies 与 sheet-removal-parts 共 28 项定向通过；
engine TypeScript noEmit 通过。既有 table-read 精确对象断言补上原已存在的
filterButton:true。未运行完整套件、bundle 或提交推送。
