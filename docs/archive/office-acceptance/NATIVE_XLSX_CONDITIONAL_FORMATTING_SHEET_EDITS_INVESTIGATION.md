# 条件格式：工作表重命名与标签重排调查

最初调查仅新增隔离回归和浏览器探针；随后生产窗口开放，已完成下述引擎修复。调查基于 GenOffice 固定提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 已确认的边界

引擎回归 `reporting/workbook_engine/packages/xlsx-engine/tests/conditional-formatting-sheet-edits-gap.test.ts` 共 8 例，当前 **4 通过、4 失败**，日志 `/tmp/cf-sheet-edits-engine-investigation.log`。

通过的对照包括：

- 普通表达式按原大小写引用工作表时，可以重命名并同时调整标签顺序；中文及带单引号的名称正确转义。
- 字符串字面量中的 `Source!A1` 保持原文；前置 `TRUE` / 红色 / `stopIfTrue` 规则保持优先级。
- 只改变标签顺序时，两个工作表 XML 和 styles.xml 内容完全不变。

失败的契约包括：

- 实际表名 `Source`，公式为 `source!A1>0` 时，重命名后仍引用旧表名。
- 公式为 `Source!a1>0` 时，同样没有跟随重命名。
- 普通 dataBar 的 `<cfvo type="formula" val="Source!A1"/>` 未重写。
- linked dataBar 中，x14 的 `<xm:f>` 已重命名，但基础规则的 `cfvo@val` 仍为旧表名，形成两套公式不一致；当前读取结果 `issues=[]`。关联 ID、负值色、gradient 和前置规则对照仍保持。

## 浏览器证据

隔离探针：`frontend/smoke/workbook-cf-sheet-rename-gap-probe.mjs`。使用真实 openpyxl 工作簿、开发服务器与 Univer `sheet.command.set-worksheet-name` 命令，将 `Source` 改为 `财务 O'Brien`。

日志 `/tmp/cf-sheet-rename-browser-red.log` 显示：重命名、撤销和重做命令均返回成功，但 Other 上的条件格式始终为 `=Source!A1>0`，未变为 `='财务 O''Brien'!A1>0`。规则 ID、前置 TRUE/stopIfTrue 顺序和撤销/重做原状对照通过；页面没有异常。探针按预期以断言失败退出。

因此，后端处理普通表达式已有部分支持，不代表编辑器内条件格式会跟随工作表改名。当前未对该浏览器探针增加保存或 rev2 验收，不能据此声称保存链路已验证。

## 源码定位

- 固定来源：`packages/xlsx-gateway/src/gateway/xlsx-sheets.ts`，SHA-256 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。其 `renameSheetInFormula` 和 XML 重写覆盖普通公式节点，未覆盖 cfvo 的公式属性；固定来源也未包含 xm:f 重写。
- 本地 `packages/xlsx-engine/src/sheets-edit.ts`：引用正则使用 `gu` 并匹配大写 A1，表名比较使用严格大小写相等；XML 已额外覆盖 xm:f，但未覆盖 cfvo@val，因而可出现基础/x14 两侧不一致。
- 本地 `sheet-ops.ts::applySheetEdits` 对所有源工作表执行上述改名，再重排工作簿标签。
- 编辑器 `workbook-data-validation-structure.ts` 对重命名有数据验证跟随处理；现有共享 CF 结构事务依赖行列/单元格移动 spec，重命名没有对应 spec。
- 安装的 Univer `sheets-conditional-formatting-ui` 将公式交给 `FormulaRefRangeService.registerRangeFormula`。该服务依据 `getSeparateEffectedRangesOnCommand` 跟随变化；后者在当前安装版本仅列举区域/行列结构命令，没有工作表重命名分支。普通公式另有重命名处理，不能推定它已覆盖 CF 规则体。

## 后续最小实现范围

1. 共用工作表改名公式变换，覆盖 CF 普通公式、公式阈值属性和 linked xm:f；保留字符串、原始视觉扩展、关联 ID、规则范围与优先级。
2. 支持合法表名/单元格引用的大小写等价，并增加外部引用保护回归；linked 双侧更新后应验证语义一致。
3. 编辑器重命名事务同步 CF 规则体，精确记录撤销/重做，保持父规则 ID、顺序和 stopIfTrue。
4. 保留标签重排的字节不变对照，新增实际保存、重新打开和 Python 验收后再宣称闭环。

## 引擎修复与验收

后续生产窗口保留来源 serializer，改造本地共享 `renameSheetInFormula`：表名大小写等价、A1 大小写等价，保留实际 token 拼写；未引用的 `[book.xlsx]Source!A1` 和引用的 `'[book.xlsx]Source'!A1` 均保持原文。普通公式、cfvo@val 和 xm:f 共用该变换。前端可直接导入此 API，前端事务和实际保存验收由对应执行者补充。

reader 对 linked 两侧 cfvo 的数量、类型、数值及公式一致性进行独立验证。兼容基础 min/max 与 x14 autoMin/autoMax 的既有对应关系；公式只规范化函数/引用大小写、等价工作表引号及可选等号，保留字符串值和交集空格。缺失公式、旧表名、不同字面量或类型/数值差异记录 `CF linked extension threshold differs from its base rule`，不再返回无问题的完整规则投影。原始 XML 仍由快照保留。

扩展回归首先得到 **10 失败 / 5 通过**（`/tmp/cf-sheet-edits-expanded-red.log`），修复后 **15 通过**。新增对照验证改名时无关源工作表和 styles.xml 内容不变。定向运行此文件、snapshot 和 sheet-ops 三文件共 **135 通过**（`/tmp/cf-sheet-edits-final-green.log`），引擎及桥接严格类型检查通过（`/tmp/cf-sheet-edits-engine-types.log`）。未重跑旧 cell-shift/split 完整测试，未构建 bundle/dist/static。浏览器调查 RED 是原始缺口证据，不代表后续前端验收状态。

## 前端改名事务及开发态完整验收

前端新增 `planNativeConditionalFormattingRename`，仅递归变换带 `type/subType=formula` 的公式值，共用文件引擎 `renameSheetInFormula`；普通表达式、dataBar/色阶公式阈值使用同一限定符语义。完整来源/结果schema和预算通过后，复用既有完整有序Delete/Add事务；保持每个原cfId、范围、父槽位与stopIfTrue，undo恢复原始规则body。collector在改名前为所有规则sheet整体预检并替换官方CF followers，不把改名塞进ShiftSpec，也不接受客户端linked来源mapping。

`/tmp/workbook-cf-rename-frontend-red.log` 记录两个真实缺失：改名wrapper不存在及collector仍接受旧官方followers。`/tmp/workbook-cf-rename-frontend-green2.log` 19项通过，包括大小写、字符串/外部簿保护、公式阈值、原id/order/undo及未知规则失败整批不变；`/tmp/workbook-cf-rename-frontend-types.log` tsc exit0。

root bridge bundle `/tmp/office-cf-rename-engine-bundle.log` exit0后，真实开发态探针 `smoke/workbook-cf-sheet-rename-probe.mjs`（4221）完整exit0：`/tmp/workbook-cf-sheet-rename-dev-final.log`。Source改为`财务 O'Brien`后，大小写普通表达式、普通dataBar公式阈值与linked基础/x14两侧公式均正确转义并跟随，字符串中的Source!A1不变。原生undo精确恢复原id/body，redo、真实draft reload、Python patch/openpyxl及修订2重开均通过。

保存仅提交applySheetEdits，无CF snapshot。实际ZIP中base cfvo公式与xm:f一致；linked-rename-id、gradient=0、负值红色原样保留；顺序priority1/2/3/4不变。只有workbook.xml与Other对应sheet2.xml变化，Source worksheet与styles.xml字节不变，Other值不移动，pageErrors=[]。HTTP context/save/revision由probe提供、文件处理为真实Python，不能宣称生产HTTP端到端。

纯UI静态探针 `smoke/workbook-cf-sheet-rename-built-smoke.mjs`（4222）走真实sheet tab双击重命名、原生CF管理器、File undo/redo、draft/Python/rev2及实际JS200/SHA；等待最终静态结果，以上开发态成功不替代静态验收。

## 最终纯UI静态验收通过

root统一 `/tmp/office-cf-rename-word-mirror-build.log` 40.37s exit0，对应budget/contract exit0且未提高cap。最终 `/tmp/workbook-cf-sheet-rename-built-final3.log` 进程exit0：完全不注入或访问runtime，真实标签双击改名、File undo/redo、管理器四范围和自定义公式入口、draft reload、实际Python patch/openpyxl保存及修订2重开全部通过。333个实际JS响应HTTP200且与磁盘SHA256匹配；main `lazy-workbook-main-NRM-WSGM.js`，engine `lazy-workbook-engine-BMpvh_QZ.js`，collector `lazy-workbook-structure-followers-ByVcUCp-.js`，pageErrors=[]。

实际保存严格仅applySheetEdits。普通表达式及两条dataBar公式阈值正确跟随，linked base/xm:f一致、linked-rename-id/gradient0/负值红色保留，priority1/2/3/4不变；仅workbook.xml与sheet2.xml变化，Source worksheet及styles.xml保持字节不变。管理器公式值由canvas渲染，纯UI探针不通过DOM强读正文，以真实保存XML作值与双侧一致性的权威断言；开发态探针另已核原生完整id/body。

前两轮probe失败保留：`/tmp/workbook-cf-sheet-rename-built-manager-selector-red.log` 记录列表只显示“自定义公式”而无正文；`/tmp/workbook-cf-sheet-rename-built-dom.log` 记录真实编辑器canvas/空contenteditable；`/tmp/workbook-cf-sheet-rename-built-final2.log` 记录fill改标签文字后旧Source定位失效。仅修probe定位为稳定sheet-tab editable，未改生产、删业务断言或重建static。

上述完成工作表改名CF跟随缺口，不覆盖删除工作表的依赖扫描/前置拒绝等独立后续边界。
