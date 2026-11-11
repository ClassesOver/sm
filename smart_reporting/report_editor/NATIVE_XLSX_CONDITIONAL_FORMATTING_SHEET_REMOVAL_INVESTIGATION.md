# 条件格式：工作表删除依赖调查

本轮仅新增独立测试、浏览器探针和本文档，未修改生产、来源清单或构建产物。固定 GenOffice 提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 来源契约

`packages/xlsx-gateway/src/gateway/xlsx-sheets.ts` 文件说明明确约定：工作表被引用时删除失败关闭（removals fail closed when anything still references the sheet）。该文件 SHA-256 为 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。

本地 `sheet-ops.ts::applySheetEdits` 同样在修改 ZIP 前扫描其他工作表、图表与存续定义名称；检测到依赖时拒绝。`tests/sheet-ops.test.ts` 已有普通单元格公式的拒绝契约。因此本轮按来源的拒绝语义核验，不要求转为 `#REF!`；普通条件表达式被拒绝是正确行为。

## 引擎证据

新增 `reporting/workbook_engine/packages/xlsx-engine/tests/conditional-formatting-sheet-removal-gap.test.ts`。仅运行此文件：**3 失败、8 通过**，日志 `/tmp/cf-sheet-removal-investigation.log`。

通过：

- Other 的普通表达式引用 `Source!A1`、`source!a1` 和 `'Source'!$A$1` 时拒绝删除 Source。
- source reader 验证完整、基础与 x14 阈值相符的 linked dataBar，通过 xm:f 依赖正确拒绝删除；未将 linked 异常输入伪装为完整输入。
- 只有 TRUE、字符串字面量或外部工作簿引用时允许删除；Other 工作表 XML 与 styles.xml 保持不变。

失败：dataBar、colorScale、iconSet 三种规则使用普通 `<cfvo type="formula" val="Source!A1"/>` 时，删除操作实际成功，没有拒绝。`worksheetReferencesSheet` 只扫描 f、formula/1/2 和 xm:f，不扫描公式 cfvo@val。重命名已覆盖阈值属性，不代表删除依赖检测已覆盖。

## 浏览器证据

新增 `frontend/smoke/workbook-cf-sheet-removal-gap-probe.mjs`，独立 Vite 端口 4223，真实 openpyxl Source/Other 文件。Other 按顺序包含 TRUE 红色 stopIfTrue 与 `Source!A1>0` 绿色规则。

日志 `/tmp/cf-sheet-removal-browser-investigation.log`：

- `sheet.command.remove-sheet` 返回 true，工作表名称列表变为 `["Other"]`。
- 条件格式仍保留 `=Source!A1>0`，ID、顺序与前置 stopIfTrue 保持。
- undo 返回 true 并恢复 `["Source","Other"]`；redo 再次删除 Source，条件格式依旧不变。
- 页面无异常；稍后反馈为 `本地草稿暂未更新：工作表 "Other" 的公式仍引用 "Source"，已拒绝删除。`
- 探针对“引用存在时工作表不得先删除”的契约实际断言失败。

这说明后端拒绝发生在 UI 已变之后，缺少与来源一致的原子前置检查。此探针未提交保存或重新打开，不宣称完整保存链路已验收；页面草稿失败消息是直接观察到的附加证据。

## 最小后续范围

1. 复用现有 `formulaReferencesSheet`，完整扫描公式 cfvo@val，保护大小写、字符串与外部簿边界；不要修改来源 serializer 或替换为自造 #REF 语义。
2. 浏览器删除 command 在任何基础 mutation、followers 或历史登记前检查存续规则的依赖，并按同一拒绝契约保留原工作表、规则、顺序和撤销栈。
3. 不能仅检查 live wire 投影：incomplete/linked 等原始 XML 的依赖保护仍应沿用实际源文件。删除本身会移除的工作表不应误计为存续依赖。
4. 新增前置拒绝、取消后无 dirty/history/draft 变动以及无依赖删除的真实 GUI/保存对照；linked 规则保留 ID、视觉字段与父优先级。

## 引擎修复验收

后续生产窗口仅在 `worksheetReferencesSheet` 增加公式 cfvo 属性扫描，复用已有 `formulaReferencesSheet`，未修改来源 serializer 或删除语义。原始 3 RED 均转 GREEN；删除专项加现有 sheet-ops 共 **30 通过**（`/tmp/cf-sheet-removal-engine-green.log`），引擎与桥接类型检查通过（`/tmp/cf-sheet-removal-engine-types.log`）。

另补 6 个阈值专项对照：lowercase A1、quoted sheet case 均拒绝；Other 引用、XML 转义字符串以及 quoted/unquoted 外部工作簿仍允许，Other 工作表 XML 与 styles.xml 保持原文。扩展删除专项 **17 通过**（`/tmp/cf-sheet-removal-threshold-final-green.log`）。

引擎已修复，浏览器原子前置检查由前端负责，不能由本节引擎结果推定完成。未重跑 rename、cell-shift 或其他旧完整测试集；未构建 bundle/dist/static。

## 原生 Python 调用验收

`reporting/tests/test_workbook_conditional_formatting_structure.py` 新增 21 个真实 openpyxl ZIP / `patch_office` 参数用例，使用已由 root 打包的 engine：三类阈值 × 三种本地表引用共 9 个拒绝用例通过；三类阈值 × Other/字符串/quoted 和 unquoted 外部簿共 12 个允许用例通过，且剩余工作表与 styles.xml 字节完全相同，内容、字体、填充、priority 与 stopIfTrue 保留。

首次执行 `/tmp/cf-sheet-removal-native-python.log` 的 9 个拒绝用例通过；12 个允许用例因新增测试插入时误带旧测试末尾断言失败，恢复旧断言原位后仅重跑受影响允许用例，`/tmp/cf-sheet-removal-native-python-allowed-green.log` 显示 12 通过、14 未选。未重跑既有完整套件。此结果证明 Python→打包 engine 的阈值拒绝与无本地依赖删除边界；前端纯 UI 与保存链路仍由对应执行者独立验收。

## 前端原子检查及开发态验收

新增 `assertConditionalFormattingSheetRemoval` 复用 `formulaReferencesSheet` 检查存续live CF普通表达式及三类视觉公式阈值。完整投影以当前编辑为准，不从旧来源恢复已清除的依赖；不完整来源通过root可信source callback，仅抽取原始普通CF/x14 CF块交给 `worksheetReferencesSheet`，不扫描旧普通单元格公式。被删除工作表自身规则不计入存续依赖。collector在调用任何原有collector或执行基础mutation前执行第三source callback与live检查，失败不登记followers。

`/tmp/workbook-cf-sheet-removal-frontend-red.log` 记录缺失helper的10项RED；实现后扩展12项全部通过 `/tmp/workbook-cf-sheet-removal-frontend-green1.log`，覆盖大小写、quoted、三视觉阈值、字符串/external允许、incomplete原XML及旧complete不误拒。collector定向 `/tmp/workbook-cf-sheet-removal-collector-green.log` 证明拒绝时original调用数0，原result/ownership不变，无依赖时返回原结果。`/tmp/workbook-cf-sheet-removal-frontend-types.log` tsc exit0。

真实开发态 `smoke/workbook-cf-sheet-removal-probe.mjs`（4224）默认引用拒绝 `/tmp/workbook-cf-sheet-removal-dev-refusal.log` exit0：deleted=false，原sheet names/cfId/body/order不变，undo/redo均false，localStorage草稿与saveLabel不变，无保存请求、pageErrors=[]。独立原无依赖对照 `/tmp/workbook-cf-sheet-removal-dev-allowed.log` exit0：删除、undo/redo、draft、Python保存和修订2重开通过，Other XML/styles字节不变。

新增关键路径 `CF_REMOVAL_CLEAR_SOURCE=1` `/tmp/workbook-cf-sheet-removal-dev-clear-source.log` exit0：原来源有依赖先被拒绝且无草稿/dirty变化，真实管理器删除第二条依赖规则后，允许删除Source，undo/redo、draft、真实Python/openpyxl保存和修订2重开均通过。实际payload严格先replaceSheetConditionalFormats Other保留TRUE/stopTrue，再applySheetEdits删除Source；styles字节不变，剩余数据/priority保留，pageErrors=[]。该保存顺序由root main两阶段prefix计划实现，不能仅依赖前置检查允许。

纯UI静态探针 `smoke/workbook-cf-sheet-removal-built-smoke.mjs`（4225）已准备：真实tab右键删除及确认，拒绝时无dirty/history/draft，真管理器清除依赖后删除/history/draft/Python/rev2及实际JS200/SHA；等root统一build预算READY。开发态HTTP context/save/revision由probe提供、文件处理为真实Python，不宣称生产HTTP端到端或chart/defined-name等全部依赖类型已原子支持。

## 最终纯UI静态关键链通过

root统一 `/tmp/office-removal-word-stability-build.log` 40.45s exit0，对应budget/contract exit0且未提高cap。`CF_REMOVAL_CLEAR_SOURCE=1 node smoke/workbook-cf-sheet-removal-built-smoke.mjs` 最终进程exit0，证据 `/tmp/workbook-cf-sheet-removal-built-clear-source-final3.log`。不注入或访问runtime：真实标签右键删除/弹窗确定先拒绝，Source/Other均在，真实File undo/redo不改变名称、管理器两规则、localStorage草稿与saveLabel；随后真管理器删除依赖，标签删除、undo/redo、draft reload、Python/openpyxl保存、修订2重开通过。

保存严格先replaceSheetConditionalFormats Other只留TRUE/stopTrue，再applySheetEdits移除Source；保留priority1、值1..5和styles.xml字节原样。333个实际JS均HTTP200并与磁盘SHA256匹配；main `lazy-workbook-main-C0LkXP2Y.js`，engine `lazy-workbook-engine-DHUBPuWA.js`，collector `lazy-workbook-structure-followers-DAPCydf4.js`，pageErrors=[]。

首轮探针选错删除弹窗“确认”（实际“确定”），保留 `/tmp/workbook-cf-sheet-removal-built-confirm-selector-red.log` 与真实DOM `/tmp/workbook-cf-sheet-removal-built-confirm-dom.log`。第二轮误假设空历史Ribbon按钮disabled；该UI未接canUndo状态，空栈按钮仍可点击，证据 `/tmp/workbook-cf-sheet-removal-built-clear-source-final2.log`。仅将probe改为真实点击undo/redo后核原状，开发态另已核undo=false/redo=false；未改生产、跳过原子性/保存断言或重建static。
