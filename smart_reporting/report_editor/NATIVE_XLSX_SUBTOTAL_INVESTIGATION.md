# XLSX 分类汇总：固定源保存调查与最小迁移方案

日期：2026-11-10。固定源：`/home/junge/pros/genoffice-source-full`，只读核对 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只新增此调查文档和 `/tmp/xlsx-subtotal-gap/` 探针，不修改生产、公共测试、gap 索引，不提交、不推送、不运行产品构建或全量测试。

## 结论与证据层次

**本地缺少分类汇总 UI/执行闭环，但固定源确实能生成可保存的分类汇总，不是只有按钮标签。** 源生成普通单元格、原生 `SUBTOTAL` 公式及两级行 outline，没有独立的“分类汇总对象”part。本地已有 `applyRowColumnOps`、`applyCellEdits`、`applySheetOutline` 可以复用；本次已用它们产生实际 XLSX 并独立回读。当前仍是调查结论，不能记作本地功能交付。

验证严格区分：

1. **真实源函数及文件保存**：AST 原样抽出源 `handleCreateSubtotal`/`recordSubtotalOutline`（不重写函数体），以可观测 worksheet facade 记录操作；调用固定源真正的 `applyCellEditsToXlsx`/`planCellEditsToXlsx`，产生 sum/count/average 三份 XLSX。只有 translation、列名、outline/journal 边界是探针适配。facade 已有公式随插行迁移使用固定源 `shiftFormulaText`，没有把静态拼出来的公式冒充真实 UI。
2. **真实 Univer 运行**：把同一源函数交给真实 headless Univer + sheets + formula engine + sheets formula，执行插行、写值、加粗和计算；得到汇总值 30、70、100 及正确公式。捕获真实 insert mutation，读取实际写入格，再交固定源 gateway 保存为第五份 `source-native.xlsx`。使用的本地依赖 core/sheets 均为 **0.25.1**，与固定源 package-lock 对应版本一致；不是完整源 React/App/Electron 宿主。
3. **本地可复用 core**：独立调用本地三个上述函数产生 `local.xlsx`，没有引入新 writer。
4. **独立回读**：Python `zipfile.testzip` + lxml + openpyxl 对五份文件读取、断言公式、行级别、尾行、加粗、跨表引用、命名区域。没有用生成方 reader 自证；没有真实 Excel/LibreOffice 桌面或完整浏览器验收。

探针中只 bundle 临时脚本，不是产品 build。复现资料均在 `/tmp/xlsx-subtotal-gap/`：`build.mjs`、`source.ts`（AST 抽出函数）、`source.cjs`、`fixture.py`、`probe.mjs`、`results.json`、`native-probe.mts`、`native-results.json`、`local-probe.mts`、`readback.py`、`readback.json`；输入 `input.xlsx` 与五份输出一并留存。`results.json` 有 14 个源 facade 向量，`native-results.json` 有 3 个真实 Univer 向量；它们不是 17 个产品验收用例。

## 从 subtotal-open 到真正保存

路径均相对于固定源根目录：

| 阶段 | 稳定符号 / 文件 | 实际行为 |
| --- | --- | --- |
| Ribbon | `apps/sheets/src/renderer/ExcelShell.tsx` `Data`/Outline 组 | 按钮调用 `onCommand('subtotal-open')`；`dispatchCommand` 只打开 `showSubtotalDialog`。 |
| 对话框 | `SubtotalDialog.tsx` `SubtotalConfig` | 输入为绝对零基列号 `groupCol/valueCol` 和 `agg: sum/count/average`。一个分组列、一个值列；字段来自 `onGetPivotFields()`。取消、遮罩或 modal close 只调用 `onClose`，没有写入。确认调用 `onCreate`，返回 null 关闭，有错误则留在对话框。 |
| 宿主委托 | `App.tsx` `dataToolsContext`、`onCreateSubtotal` | 把当前 runtime、lazy state、message/pending refs 交给 `handleCreateSubtotalImpl`。没有冻结打开时的 workbook/sheet/range 身份；确认时读取实时活动表和实时选区。 |
| 汇总算法 | `data-tools-actions.ts` `handleCreateSubtotal` | 首行为表头、body 至少一行；相邻行按 `String(value ?? '')` 比较，变化即分组，**不排序**。最多 200 组。底向上为每组插入一行，写 `标签 Total` + SUBTOTAL，再插 Grand Total；标题和值格加粗。 |
| outline | 同文件 `recordSubtotalOutline` | 明细与组计全部 level 1，再把各组明细覆盖为 level 2；grand total 没有 level。直接登记 `set-rows-outline` structural journal，并改 `sheetOutline(state,sheetId)`。不登记 summaryBelow 设置。 |
| 变更捕获 | `App.tsx` `ROW_COLUMN_MUTATIONS` 处理及 `edit-journal.ts` | 原生 `sheet.mutation.insert-row` 变为 `insert-rows` journal，并迁移 cell journal/outline/依赖；set-range-values/style 的原生 mutation 进入单元格编辑 journal。不是 subtotal 函数自行保存整表。 |
| 保存宿主 | `save-actions.ts` `toSaveEdits`、`toSaveStructuralOps`、desktop save request | 把 cell edits 和按序 structural ops 发送 desktop API；保存使用源文件身份和 scope。已有 pivots/tables/defined names 的 held/split-save 逻辑属于通用保存，不应由分类汇总另造。 |
| OOXML 落盘 | `packages/xlsx-gateway/src/gateway/xlsx-gateway.ts` `applyCellEditsToXlsx` → `planCellEditsToXlsx` | 结构移位先作用于源 XML，再在最终坐标写编辑格；`xlsx-structure.ts` 处理本表/跨表公式、名称等。实际组装 ZIP，不是 session-only。源 gateway 对仍读取来源表的 pivot cache 插行采用拒绝保护，不能假定所有依赖均可自动迁移。 |

`count` 使用函数号 **3/COUNTA**，不是 COUNT；sum 是 9，average 是 1。界面没有多值列、多级分类、替换现有分类汇总、移除全部、每组分页、汇总置顶等选项。不能把这些 Excel 完整能力算成“漏搬源已有实现”。

## 五份真实文件回读结果

输入 Data 为 A1:C6：表头、A/10、A/20、B/30、B/40、Tail/99；实际选择 A1:C5。Dependent 有 `=Data!$B$4`、`=SUM(Data!B2:B5)`；全局 Body 名称为 `'Data'!$A$2:$B$5`。

| 检查 | 五份文件共同结果 |
| --- | --- |
| 行序 | 第 4 行 A Total、第 7 行 B Total、第 8 行 Grand Total；Tail/99 移到第 9 行，原始明细不丢。 |
| 公式 | B4=`SUBTOTAL(n,$B$2:$B$3)`、B7=`SUBTOTAL(n,$B$5:$B$6)`、B8=`SUBTOTAL(n,$B$2:$B$7)`；n 分别为 9/3/1。插入第一组汇总时后组公式正确迁移。 |
| outline | Excel 第 1–9 行 level `[0,2,2,1,2,2,1,0,0]`；全部 hidden/collapsed 为 false。输入默认 summaryBelow=true 被保留。 |
| 样式 | 六个汇总标签/公式格 font.bold=true。 |
| 跨表引用 | Dependent 的绝对引用变为 `=Data!$B$5`，范围变为 `=SUM(Data!B2:B6)`；绝对 `$` 不阻止插行迁移。 |
| 命名区域 | Body 变为 `'Data'!$A$2:$B$6`。插在原范围尾端之外的组计不会被强制纳入已有范围，符合这次源行为。 |
| ZIP 改动 | `xl/worksheets/sheet1.xml`、`sheet2.xml`、`xl/styles.xml`、`xl/workbook.xml`；无“subtotal part”。ZIP CRC 全部通过。 |

五份文件此次保存均没有总计计算缓存，openpyxl data_only 读取三个总计均为 None；不能把“公式文本正确”说成 XLSX 已含已计算值。真实 Univer **会话内**计算值为 30、70、100，读取后交 gateway 保存也未自动写入公式缓存；计算与缓存的不同证据分别见 `native-results.json` 和 `readback.json`。本次没有额外传入通用保存链的 `formulaValues` 参数，不据此判定源完整宿主一定丢缓存。本地 core 文件证明保存能力，尚无产品 UI/撤销/草稿/下载重开验收。

## 取消、撤销、保护和源问题

| 项目 | 证据及边界 | 迁移处理 |
| --- | --- | --- |
| 确认前取消 | `SubtotalDialog` 无 preview 写入，只有 OK 才调用源函数；本次是源码事实，未点完整源浏览器 dialog。 | 保持取消零变更，不能打开即改表。 |
| 未排序/值相等定义 | facade 的 A/B/A 形成三组；数字 1/字符串 '1' 合组，null/空串合组。源明确要求先按分组列排序。 | 首版按源相邻分组，不自动排序；UI 说明相邻分组及 COUNTA。字符串归一化是明确的源边界，语义变化另行设计。 |
| 范围/配置校验缺失 | same-column、header-only、201 组均返回错误且零写入；但 groupCol=99 或 valueCol=99 仍继续写入。source handler 不验证 integer/范围/agg 运行时枚举。 | 确认前按捕获选区验证列号、函数、行数、最终网格上限和操作预算。拒绝必须在任何插行前完成。 |
| 中途异常不原子 | facade 第二次 insert 抛错，源返回错误，但第一组插行和两个汇总格已经保留，无 rollback。 | 先构造完整计划及依赖预检；提交过程中每条原生命令返回失败/异常必须回滚整个批次。不可把失败候选留进草稿。 |
| 原生命令被拒绝仍报成功 | **真实 Univer** `BeforeCommandExecute` 取消全部写命令时，无单元格变化，但源返回 null 并登记 6 行 outline。仅取消 insert、允许 set-value 时，源继续覆盖旧数据：原 B/30 被 A Total/30 覆盖，Tail/99 被 B Total/40 覆盖，Grand Total 变为 70。`insertRowsBefore`/`setValue` facade 不向调用方传回底层 false，源没检查。 | 本地必须沿 `ICommandService.syncExecuteCommand` 检查结果；预检受保护/未知状态，禁止直接照抄 facade 写法。 |
| 工作表保护语义 | 源 `sheet-protection.ts` `installSheetProtectionGuard` 按 insertRows/edit/formatCells 分别检查权限，使用的拒绝方式就是 `BeforeCommandExecute` 的 cancel。以上拒绝探针是**真实同版 Univer 事件等效注入**，未安装完整源保护 guard/文件状态。足以证实源 handler 忽略拒绝，不能称已完成源保护端到端。 | 复用本地 `workbook-protection.ts`：受保护表整体只读；不能为 subtotal 绕过已有保护契约，也不扩大到源 allow-edit-ranges 语义。保存端继续 `assertProtectionRespected`。 |
| Undo 非一件事 | 真实 Univer 正常场景需 **15 次 undo 才恢复输入的单元格值**；单次 undo 不是整个分类汇总。源 outline 写 journal 在命令外；探针撤销后 6 个 outline entry 仍在。探针没有安装完整 App 行列 listener，故不把这个 entry 数当成完整源保存后残留定量结论；源码能确认没有 subtotal 原子 undo/outline 快照恢复。 | 单次 Undo/Redo 必须覆盖插行、汇总格、格式、outline 与 journal；失败回滚亦恢复以上状态。复用现有 UndoRedoService 批次模式，注意 0.25.1 undo 组顺序问题。 |
| summaryBelow 与旧 outline | 源无 summaryBelow=true journal；固定算法按汇总在下生成，却沿用现有 sheet summary 设置。已有 outline 行被 set 覆盖，也未保存事务级原值。此项为源码推导，本次未测 summaryAbove 文件。 | 计划显式指定 summaryBelow=true，精确保留/恢复其它 outline 元数据；原有复杂重叠 outline 首版可以明确拒绝。勿宣称已验证该兼容场景。 |
| 过期目标 | modal 的 fields 由打开/渲染时源字段产生，提交函数重新取当前 range/sheet；没有捕获目标身份或版本。 | 冻结 workbook/sheet core 身份、选区和 generation；确认前校验仍匹配，切表/换文件/结构变化时提示重新打开。 |

这些是源行为或缺陷，不是应该逐字复制的迁移要求。特别是安全拒绝/依赖保护只拒绝本次编辑数据，不得影响已生成并核验身份的报告 PDF/Word 下载签发。

## 可直接实施的最小协议与文件落点

**首版范围按真实源限定：相邻单列分组、单值列、三种聚合、总计在下、最多 200 组。** 不在本项附带高级筛选、透视创建、图表、完整 Excel 汇总管理。

1. 新建 `frontend/src/workbook-subtotal.ts`：`SubtotalInput = { groupCol: number; valueCol: number; agg: 'sum'|'count'|'average' }`，纯计划函数返回反向 insert 列表、**最终坐标**的汇总格编辑及 outline patch。所有列号零基、结构操作按执行顺序；规划阶段先校验 header/body、同列/越界/枚举/预算/网格扩容/已存在 subtotal 与复杂 outline 冲突。目标捕获使用本地 workbook/sheet core 身份 + 选区 + generation，不以 sheetName 作为会话唯一身份。
2. 同文件的提交函数交给 `ICommandService` 检查每次执行结果，复用 `workbook-data-table.ts` 的 UndoRedoService 批次及反向 undo 经验，把结构、单元格/样式、outline 自定义 metadata/journal 作为一个事务。对批次中第 N 条命令拒绝/抛错做反向恢复，移除失败历史；不要靠最后 `setMessage` 或 facade 返回 this 判断成功。完整依赖预检用现有本地结构路径，尤其透视来源、跨表 sparkline、chart/CF/DV/表/名称，预检应在首条原生命令前完成。
3. 新建 `frontend/src/workbook-subtotal-dialog.ts`：原生 modal，三个源输入及选区列标题、相邻分组/COUNTA 提示；Cancel/Escape/backdrop 均零写入。输入校验和提交失败原因留在 dialog。可在 OK 前显示将增加的行数，无需异步预览写表。
4. `workbook-main.ts` 仅加 `subtotal-open` 捕获、dialog 生命周期、回调和 disposal；`workbook-ribbon.ts` 仅给已有 action 加 command 并去掉该 disabled reason。行列 mutation 仍由已有 structural journal 捕获，单元格 diff/outline 仍由已有保存链导出；避免将同一编辑同时塞 staged 与 live diff 导致重复插行。
5. **不需要新增 OOXML subtotal writer、下载接口或 server op kind**。实际持久化沿现有协议：`applyRowColumnOps(Data, inserts)` → `applyCellEdits(final-coordinate edits)` → `applySheetOutline(rows, summaryBelow:true)`。本次 `local-probe.mts` 已验证组合。源/本地保存的跨表公式与定义名修正属于 structural 引擎，不能复制为分类汇总私有算法。若后续命令间允许别的编辑穿插，必须让既有 journal 正确迁移这些最终坐标，不能固定持久化一份过期 plan。

落点中的 `frontend/` 相对于本文件目录，core/bridge 分别是 `../reporting/workbook_engine/packages/xlsx-engine/src/{sheet-ops,workbook-write,outline}.ts` 与 `../reporting/workbook_engine/bridge/operations.ts`。本地已有 bridge schema 对 outline level 0–7、行列边界做校验；本项不应修改白名单，除非实施时确实发现新增协议需求。

## 最小专项验收用例

| 用例 | 必须观察的结果 |
| --- | --- |
| 三聚合真实保存 | sum/count/average，各至少两组、带表后尾行和其它列；实际下载 ZIP + openpyxl 回读公式、outline、粗体、尾行；真实原生计算分别断言，COUNT 用文本/空值区分 COUNTA。 |
| 选区偏移及公式源 | 从 C5 等非原点开始、绝对列号；已有公式值/空组/未排序 A/B/A；生成行与公式最终坐标精确。不能只测 A1:B5。 |
| 取消/目标变化/输入拒绝 | Cancel/Escape/backdrop、切表/换文件/来源结构变化、同列、越界、非法函数、201 组、接近网格尾部/预算；所有失败场景零变化、零历史、零草稿。 |
| 撤销恢复 | 一次 Undo 回到原 cell/style/outline/journal/依赖，Redo 完整重现；操作前已有隐藏/分组状态不丢，summaryAbove 必须明确规范或拒绝。 |
| 故障与保护 | 第一/中间/最后原生命令返回 false 或 throw，始终整件回滚；受保护/未知目标零写入，不出现“插行拒绝但覆盖旧行”。保存端拒绝伪造草稿绕过保护。 |
| 跨表与复杂依赖 | 本次 Dependent/Body 范例；现有 table/chart/CF/DV/notes 等按现有 structural 契约保全；透视来源与当前不能安全移位的 sparkline 等在修改前拒绝并给具体原因。 |
| 产品闭环 | Ribbon 可执行、真实保存下载、登记修订、明确新修订重开、草稿重放，不重复结构操作；验证 manifest/hash 不能代替功能证据。 |

仅运行受影响的 subtotal、结构与 outline 专项，禁止重复全量测试。本次没有更改发布/导出签发链，未运行其非阻断回归；后续若实施触碰签发阶段，必须按 AGENTS.md 登记故障注入并保持全部非阻断契约。
