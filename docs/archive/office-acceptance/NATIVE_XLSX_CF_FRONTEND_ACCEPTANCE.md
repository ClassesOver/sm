# XLSX 条件格式前端完整快照适配验收

固定来源为 `genoffice-source-full` ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`：`univer-sync.ts` 的 `collectCfStates`、`applyConditionalRules`、`buildConditionalRule`，以及 `App.tsx` 的 `cfRuleUnsaveableReason` 官方编辑前置校验。源 serializer 由 engine owner 逐字迁移并登记；此文只记录本地 frontend 宿主适配与实际验证，不代替 engine 验收。

## 实现边界

`workbook-conditional-formatting.ts` 提供三项 API：

- `withWorkbookConditionalFormatting(data, model)`：完整 engine wire 规则按优先顺序进入官方 `SHEET_CONDITIONAL_FORMATTING_PLUGIN` resource；保留其他资源；无命令导入、不增加 undo 项。来源 issues 非空不导入不完整规则，保留文件原 XML。
- `workbookConditionalFormattingOperations(model, workbook)`：读官方 worksheet 全规则，与每次传入的结构操作重放 baseline 比较，仅差异输出 `replaceSheetConditionalFormats`，包含删除全部规则。不固定初始 model，也不限制前 200 单元格。
- `validateConditionalFormattingEdit(id, params, current, source)`：使用官方 command/mutation 常量及源可落盘校验，防止不支持规则进入实时模型；检查 linked 规则完整身份、来源 unknown，以及严格范围界限。主入口负责反馈与取消，不影响无关单元格编辑。

native 数字比较单阈值使用 scalar，源 wire/read 使用数组；导入/采集双向归一。native formula（包括 cfvo）使用 `=` 前缀，wire/read 去前缀，保持源 serializer 存储约定。完整来源 CF 范围可能超过工作表有值区域，导入先 strict schema 校验再扩充 rowCount/columnCount 到最大范围，上限 1048576 行/16384 列。

`workbook-data-validation-structure.ts` 复用原有官方 interceptor collector，只把官方返回 redos/undos/pre* 中真实 CF params 对象加入 WeakSet；复制对象或伪造 source 字符串均不获归属。合法官方结构 follower 可以由主入口区别于用户 CF 编辑，最终保存仍基于结构重放后的 source 验证 linked 身份。

## 定向测试

没有重复完整测试。独立三个场景首先缺模块 RED：`/tmp/workbook-cf-frontend-red.log`。

- 完整 resource + 官方 plugin 实际模型导入、无新增 history、官方 set/delete/undo/redo、engine applyOperations/readWorkbook：最终 `/tmp/workbook-cf-scalar-history-green.log` 两项通过；早期 fixture 未触发懒加载 IUndoRedoService 导致未注册 undo，直接手工注册又与原生 service 重复，均保留失败日志，最终 fixture 通过获取真实 service 启用官方历史。
- 离屏、多区域、formula/scale/bar、unknown/linked 前置校验及维度边界：`/tmp/workbook-cf-boundary-green.log` 三项通过。公式 `=` 缺失有独立 RED `/tmp/workbook-cf-formula-red.log`，修后 `/tmp/workbook-cf-formula-green.log` 通过。
- native scalar 数字经保存/read 后不产生伪差分：`/tmp/workbook-cf-scalar-red.log` → `/tmp/workbook-cf-scalar-history-green.log`。
- 官方 CF follower 对象身份：`/tmp/workbook-cf-structure-owner-red.log` → `/tmp/workbook-cf-structure-owner-green.log`，只实际对象获准，dispose 恢复原 collector。

## 真实完整 preset 浏览器

`smoke/workbook-cf-structure-gui-smoke.mjs` 使用真实原生 UI/plugin，dev 仅注入 runtime 供诊断；HTTP context/revision/save 接口由 probe mock，但保存调用真实 Python `patch_office`，产物由 openpyxl 读取。

`/tmp/workbook-cf-structure-dev3.log` 真实近处范围插行成功，但离屏 D5001:D5100 不迁移。原因是源有效行数仅 5，默认1000行 projection 小于 CF范围，官方 RefRangeService 无法覆盖远处。扩展维度后 `/tmp/workbook-cf-structure-dev4.log` exit0：B2:B5 → B3:B6，D5001:D5100 → D5002:D5101，公式同步 `=D5002>0`；删除还原。

`/tmp/workbook-cf-manager-dev4.log` exit0：通过原生管理器双击“大于10”、输入20确认；hover原生删除图标，File undo/redo/undo；reload草稿保留20；真实Python保存/openpyxl读回两规则，远处公式仍D5001>0，A1与F1原公式保留，pageErrors=[]。上一版dev3 reload超时是probe遗漏native URL返回native.html的路由，已修probe，没有据此更改产品逻辑。

`CF_FULL_COLUMN=1` 同probe：`/tmp/workbook-cf-full-column-dev.log` exit0，整列 D1:D1048576 完整原生导入/管理器显示，页面正常、pageErrors=[]，未裁剪范围或伪造全列标记。

最终静态纯UI验收脚本为 `smoke/workbook-cf-manager-built-smoke.mjs`，不注入或访问 runtime，检查真实面板值、原生管理器编辑/删除/undo/redo、草稿、Python保存、rev2重开，以及所有实际JS HTTP200和磁盘SHA身份。等待root统一build后执行，当前不宣称built已验收。

## Linked 结构边界新增真实缺口（未隐去）

额外 `smoke/workbook-cf-linked-structure-gui-smoke.mjs` 将真实 ZIP 注入可信唯一 base/x14 twin dataBar。官方用户修改 linked identity 被正确拒绝，结构 mutation 的可信归属允许合法原生 undo/redo。但 `/tmp/workbook-cf-linked-structure-dev2.log` 暴露尚未修复的边界：源 B1:B3 在第0行前插入，官方 CF Common helper扩为B1:B4，文件引擎按源约定移为B2:B4；最终完整身份检查正确拒绝不一致快照，DOM给出“保存失败，草稿已保留 / 关联 linked 条件格式必须保持原始完整身份”。此案例不能记为可保存通过。

只读根因：Univer sheets `handleInsertRowCommon` 在 Direction.UP 使用 `insertRow < range.startRow` 才整体迁移，恰等边界只扩 end；对应列 Direction.LEFT 同理。CF `FormulaRefRangeService.registerRangeFormula` 走 Common helper，而文件 `shiftSqrefAttribute/shiftRangeReference` 逐端点使用 >=start 迁移。问题不局限0坐标。

计划由既有可信结构 collector 对官方 CF follower ranges/formulas复用源 `shiftRangedFeatures`/`shiftFormulaText` 归一，不放宽linked身份或另造坐标引擎。root当前统一build窗口要求production/static冻结，先准备 row0/row4/col0/col4 定向RED，静态验收后再实施。普通 CF manager编辑保存与非边界结构GUI已通过，不以此抹掉 linked 边界缺口。

## 最终静态普通CF闭环验收通过

root `/tmp/office-footnote-cf-budgetfix2-build.log` exit0 39.59s 后，纯UI built脚本一次完整exit0：`/tmp/workbook-cf-manager-built-final.log`。不注入或访问runtime；真实原生面板10→20、删除、File undo/redo/undo、reload草稿、Python patch/openpyxl保存、rev2重开面板20与D5001:D5100范围全部通过。原A1、F1公式和远处CF公式保留。327个实际JS均HTTP200且response与磁盘SHA匹配；main `lazy-workbook-main-9AmtWKfk.js`，engine `lazy-workbook-engine-DVmS-RV_.js`，CF serializer `lazy-workbook-conditional-formatting-Cv8Pp1A2.js`，CF controls `lazy-workbook-conditional-formatting-controls-D8wfdTGB.js`，pageErrors=[]。

该静态验收覆盖普通CF编辑保存闭环，不覆盖前节已实证失败的linked精确上/左边界结构迁移。此缺口仍需可信follower源语义适配后单独验收。

## Linked 精确边界结构保存已修复（源算法复用）

静态验收结束后获root窗口实施：engine owner仅导出现有 `shiftRangeReference`（无行为变化）；既有 collector 对官方 CF redo先整批校验 unit/subunit/cfId唯一性、支持形状，再基于执行前完整rule复用源 `shiftRangeReference`/`shiftFormulaText` 生成范围/公式，最后一次性替换payload。undo保持官方捕获原rule；复制/伪造mutation不获归属。完整删除保持官方Delete+AddUndo；产生新cfId的split或重复Set没有假装支持，会在基础结构mutation前明确拒绝，防止半迁移。

四边界（row0,row4,col0,col4）范围与公式定向RED `/tmp/workbook-cf-boundary-follower-red.log` → GREEN `/tmp/workbook-cf-boundary-follower-green.log`（含实际params归属5项）。`/tmp/workbook-cf-batch-preflight-green.log` 额外5项通过：full delete、split、duplicate、foreign unit、foreign sheet，拒绝时较早payload与WeakSet均未改变。

真实linked probe `/tmp/workbook-cf-linked-structure-dev3.log` exit0：用户修改linked身份被拒；插0行B1:B3规范为B2:B4；原生undo/redo、draft reload、真实Python保存/openpyxl、ZIP base sqref与x14 xm:sqref均B2:B4，pageErrors=[]。近处普通规则B3:B6、离屏公式D5002>0一致迁移。该新增修复在dev验证，需后续root重建static再验，不能将早先built身份当作包含此修复。

## 结构后普通编辑的可信来源缓存

主入口root发现额外真实RED：linked插行迁移后编辑另一普通规则仍拿初始linked来源，`/tmp/workbook-cf-linked-ordinary-after-structure-red.log` 返回 edited=false。root改为结构回放baseline缓存，绑定currentModel引用和sheet plan/结构内容签名；匹配才使用，未同步明确稍后重试，不从实时CF自认可信来源。

`/tmp/workbook-cf-linked-ordinary-after-structure-green2.log` 最终exit0：insert→undo→redo→普通规则20编辑返回true；等待真实localStorage草稿replaceCF的number.value=[20]后reload，恢复native20；Python保存/openpyxl读回cellIs20、linkedB2:B4、远处D5002>0，base/x14双scope均核，原A2='keep'、F2='=SUM(B3:B6)'，pageErrors=[]。此前green（无2）日志只编辑返回true即reload，尚未等异步draft采集，最终20未持久化而断言失败；probe新增真实持久化完成条件后通过，未放宽任何产品验证。

最终生产collector批次review后四边界再次定向通过 `/tmp/workbook-cf-boundary-batch-final-green.log`（4项），最终类型检查 `/tmp/workbook-cf-boundary-final-typecheck.log` exit0。新增最终built纯UI脚本 `CF_LINKED_STRUCTURE=1` 模式覆盖此结构+普通编辑+draft+ZIP双scope链，待root下一统一build。

剩余边界：当前可信迁移规范覆盖行/列插入删除；复杂跨区域公式拆分产生新cfId、同规则多个Set、拖动移动/rename复杂引用需要后续独立源语义验证。尤其官方Add会把新规则unshift到最前，不能直接接受split的全局优先顺序；现阶段预检明确拒绝未建模拆分，未声明所有结构操作全量对齐。

## 最终 linked 结构与普通编辑静态验收通过

root `/tmp/office-endnote-cf-cellis-budgetfix-build.log` exit0 39.71s，budget/contract exit0且未提高cap后，执行 `CF_LINKED_STRUCTURE=1 node smoke/workbook-cf-manager-built-smoke.mjs`，`/tmp/workbook-cf-linked-manager-built-final.log` 完整exit0。

全程不注入或访问runtime：真实功能区定位A1与插行，原生管理器普通10→20、删除、File undo/redo/undo，等待真实localStorage保存20后reload草稿，真实Python patch/openpyxl保存、ZIP base sqref和x14 xm:sqref均B2:B4，修订2原生面板重开20和D5002:D5101范围全部通过。A2='keep'、F2='=SUM(B3:B6)'、远处CF公式D5002>0、stopIfTrue保留；pageErrors=[]。

333个实际JS HTTP200并与磁盘SHA匹配：main `lazy-workbook-main-Bir0StqX.js`，engine `lazy-workbook-engine-dbMFDa5l.js`，CF serializer `lazy-workbook-conditional-formatting-Cv8Pp1A2.js`，CF controls `lazy-workbook-conditional-formatting-controls-NIF-gfZX.js`。此最终身份包括可信CF follower源算法归一与主入口结构baseline缓存修复；上面的早先built身份仅描述其历史验收。

本地最终源身份：`workbook-conditional-formatting.ts` SHA256 `20499aeaec1bf0acbb053ef2a39b7a2e3d00d23ec07408adb554f2bfc8855c48`；`workbook-data-validation-structure.ts` SHA256 `c00a51737949981a1537c8265bc1de95c6039b51109daed3ab8859f6ea668c7a`；built probe SHA256 `e413a69d9a8c26a6cb6099d879868b3c995cfbe62f042235e1e6ed55c3a40836`。复杂公式拆分/移动/rename等前述缺口仍保留，不从单fixture推广为全部XLSX/Word完成。

## Complex split 新阶段（实施中，尚未静态验收）

跨表相对公式 `Other!B1:B4 -> Source!A1>0` 在Source第2行插入时，需要保持Other覆盖不动并分成B1/Source!A1与B2:B4/Source!A3两群。固定源 `toCfFormula` 仅补 `=`；官方 `_getFormulaDependcy` 用 `rangeUnitId || 当前unitId` 解析裸Source!A1，已真实注册，无需人为加workbook前缀。官方原生返回Set B2:B5和Add B1，误多B5，且Add的unshift会越过高优先级stopIfTrue。`/tmp/cf-complex-split-official-red2.log` 与原真实probe保留此证据。

本阶段engine owner新增共享pure interval planner；前端 `workbook-cf-structure-plan.ts` 将每父有序分区flatten，保持父优先级槽；首群原cfId，其余新cfId。整批规则/预算校验后才分配身份，生成官方Delete旧集+逆序Add新集，undo Delete新集+逆序Add原集。collector在基础结构mutation前先构造所有sheet计划，成功后整体丢弃官方错误CF followers并放入共享计划，DV/table等其他mutation保留；来源未知/无法表示规则预检失败时result完全不改。

wrapper三场景先模块缺失RED `/tmp/workbook-cf-shared-plan-red.log`，实现后 `/tmp/workbook-cf-shared-plan-green1.log` 3项通过（父槽优先级、undo原id/body、unsupported全批校验、整列区间分区非枚举）。collector `/tmp/workbook-cf-collector-plan-green1.log` 4项通过，包括不信官方foreign旧CF、完整有序替换和失败时result/归属不变。

真实probe `/tmp/workbook-cf-complex-split-dev-green1.log` exit0：原高优先TRUE stopTrue保持首位，后两群B1 Source!A1 / B2:B4 Source!A3，Other不多B5，pageErrors=[]。扩展probe原生undo/redo与draft恢复三群通过，但 `/tmp/workbook-cf-complex-split-dev-save1.log` 最终真实Python旧dist仍输出原两群，不能记保存通过；等待root统一bundle新engine再重验，未修改产品迎合旧产物。

Complex split更新：root统一 `bundle:bridges` exit0 `/tmp/office-cf-split-engine-bundle.log` 后，仅重验原失败dev路径，`/tmp/workbook-cf-complex-split-dev-save2.log` 完整exit0。真实原生优先级三群、undo/redo、draft恢复与Python/openpyxl保存全部通过；实际payload只有Source insert index1结构操作，无客户端CF来源mapping，服务端可信来源重算得到ordered `[TRUE/stopTrue/B1:B4, Source!A1/B1, Source!A3/B2:B4]`，pageErrors=[]。先前旧dist失败未抹去。

新最终静态纯UI脚本 `smoke/workbook-cf-complex-split-built-smoke.mjs`（4218）已准备并通过语法检查，覆盖真实功能区定位/插行、原生管理器范围三群、undo/redo、draft、Python保存及修订2重开、实际JS HTTP200/SHA；待root下一统一build。

## Complex split 最终静态验收通过

root统一 `/tmp/office-mixed-columns-cf-split-budgetfix4-build.log` exit0（40.04s），对应budget/contract exit0且未提高cap后，最终纯UI `/tmp/workbook-cf-complex-split-built-final.log` exit0。不注入或访问runtime：跨表插行后原生管理器显示B1:B4/B1/B2:B4，File undo恢复原两群，redo恢复三群，等待真实localStorage结构草稿后reload、真实Python patch/openpyxl保存、修订2重开全部通过。保存仅提交Source insert index1；服务端可信源重算ordered `[TRUE/stopTrue/B1:B4, Source!A1/B1, Source!A3/B2:B4]`，没有客户端CF来源mapping或snapshot。

333个实际JS均HTTP200且response与磁盘SHA匹配：main `lazy-workbook-main-DNNszr8I.js`，engine `lazy-workbook-engine-DPv5fK7Z.js`，结构collector `lazy-workbook-structure-followers-KQemJlDk.js`，pageErrors=[]。context/save/revision HTTP由probe提供，文件处理使用真实Python；此为静态浏览器与真实文件保存闭环，不宣称生产HTTP端到端。

首轮脚本在undo后仍留在原生自动切回的Source sheet，等待Other范围超时；独立失败证据保留 `/tmp/workbook-cf-complex-split-built-undo-sheet-red.log`。仅修probe在每次读取管理器前通过真实UI定位Other!B1，未改生产或放宽undo断言，第二轮完整通过。

该验收完成行/列跨表相对公式拆分及父优先级缺口；单元格四方向插入/删除的空白覆盖语义、移动/rename等后续路径仍需各自验证，不扩大为全部XLSX/Word完成。
