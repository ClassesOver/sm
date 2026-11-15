# 图表引用：删除工作表只读调查

本轮新增隔离 test/probe/doc，不修改生产、manifest 或构建。真实 openpyxl 工作簿只有 Source/Other 和常量单元格，图表锚定 Other、系列引用 Source；没有 CF、DV、普通单元格公式或定义名称。

## 来源披露

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `xlsx-sheets.ts::chartReferencesSheet` 与本地一样仅匹配 `<c:f>`。默认 chart namespace/合法别名前缀的兼容并非来源已具备能力，而是后续需要明确披露的兼容修复。源文件 SHA-256 `f1b20c4fd4868b39f4fe0e0c2c3d5a462343d87c84d9f091037f778249467679`。

来源另已具备 OWNED_SHEET_RELATIONSHIP_TYPES 和 owned satellite 级联规划，含 drawing；本地 trimmed assertSheetRemovable 仍明确拒绝 drawing，不能把本地“charts or images不允许删除”描述为完整源契约。实际完整级联还需执行网关调用链核验，本轮未改级联实现。

## 引擎真实 ZIP 与 namespace 对照

`packages/xlsx-engine/tests/chart-sheet-removal-investigation.test.ts` 首批真实 2 例 **1 失败、1 通过**（`/tmp/chart-sheet-removal-engine-investigation.log`）：

- openpyxl 生成的合法默认 chart namespace `<chartSpace xmlns="http://schemas.openxmlformats.org/drawingml/2006/chart">`，内部 `<f>'Source'!$A$1:$A$5</f>` 未被识别。Source 实际删除成功，chart1.xml 原字节和 styles.xml 保持，却仍引用已不存在的 Source。
- 同一 ZIP 的 chart XML 改为正确绑定该 URI 的 c 前缀时，引擎正确拒绝。

随后仅重跑 default 用例以新增文件身份断言，`/tmp/chart-sheet-removal-engine-xml-evidence.log` 明确输出 `{sourceRemoved:true,chartXmlUnchanged:true,chartProjected:0}`；chart-read 本地同样依赖 c 前缀，默认 chart 没有投影，不代表原始图表不存在。

新增 namespace/owner 窄对照 **3 失败、1 通过**（`/tmp/chart-sheet-removal-namespace-owner-investigation.log`，未重复前两例）：合法 chart URI 的 q:f 未识别（RED）；foreign URI 却命名 c:f 被误认为图表依赖（RED）；合法 drawing main URI 的 a:f 不被当成 chart 依赖（GREEN）；图表完全归被删 Source 所有时本地仍因 drawing 拒绝（RED，来源 owned cascade 差异）。

因此后续不能简单匹配任意 `*:f` 或所有 `<f>`。必须验证命名空间 URI：chart 为 `http://schemas.openxmlformats.org/drawingml/2006/chart`，drawing main 为 `http://schemas.openxmlformats.org/drawingml/2006/main`，外来 URI 不得冒充 chart。默认继承与局部前缀重绑定都需纳入真实 XML 身份。

## 浏览器 RED

`frontend/smoke/workbook-chart-sheet-removal-gap-probe.mjs`（Vite 4231）实际删除返回 true、Source 消失、完整 snapshot 改变、undo/redo 返回 true，但 undo 完整 snapshot 不等原状。没有拒绝反馈；草稿从空存储变为持有 operations=[] 的记录。图表默认 namespace 未投影，snapshot 无图表 specs，故不能以 live charts 为空授权删除。日志 `/tmp/chart-sheet-removal-browser-investigation.log`；页面无异常，工作表/快照/历史/草稿四条原子断言失败。

草稿 operations=[] 的具体异步原因尚未定位，不能据此声称已保存删除或图表已被正确丢弃。引擎真实 ZIP 证据独立确认 chart XML 悬空引用。

## 最小后续范围

1. 以命名空间身份读取真实 chart 公式；修复默认/alias 漏查、foreign c:f误查，保护字符串、外簿和大小写。来源原 serializer 不重写，适配补丁明确披露。
2. 前端 actual package chart 来源按 model/结构签名缓存，存续 chart 依赖在任何删除 mutation/history 前拒绝。未投影图表不得从空 live snapshot 推断无依赖。
3. owner cascade 与 referenced removal分开：存续 Other 图表引用 Source 应拒绝；被删表拥有的图表是否可级联必须按来源实际关系图规划，并验证无共享/外来parts误删。本轮不将级联缺失混入最小前置扫描修复。
4. 验证 series values/categories/name/X-values 等 c:f 节点、实际图表 XML保真、完整snapshot/history/draft，以及真实保存重开。图表编辑/清除依赖需另有明确受支持的写入路径，不能假设 live charts 可编辑。

上述缺口尚未修复；所有用例是只读调查新增证据。

## 引擎 namespace 引用修复

后续生产窗口仅修复图表公式引用识别，不扩展 chart-read 投影。引擎显式依赖 saxes 6，导出 `readChartFormulas(chartXml): string[]`，以 xmlns 模式处理真实 URI、默认继承和局部重绑定；chartReferencesSheet 复用该函数。text/entity/CDATA 正确解码，合法空图表返回 []，未绑定前缀或 malformed XML 明确抛错。foreign c:f 与 drawing-main a:f 不被当成 chart f；literal/external 保持边界。

namespace 专项 13 通过，sheet-ops 19 通过，共 **32 通过、1 TODO**（`/tmp/chart-namespace-final-engine-green.log`）；TODO 是独立 owned drawing 级联，原始真实 RED 留在调查日志，不冒称对齐。engine/bridge 类型通过（`/tmp/chart-namespace-final-types.log`）。单次 bridge bundle 后新增原生 Python `test_workbook_chart_sheet_removal.py` **9 通过**（`/tmp/chart-namespace-native-python.log`）：default/alias 和大小写引用拒绝；Other/literal/external/foreign 允许，chart/drawing/rels/styles/worksheet 原字节保留。来源 c:f-only 限制作为本地兼容修复披露。

sheet-ops 仍扫描全部 xl/charts/chartN.xml，未附着 chart 也参与拒绝；前端 actual OPC owner 图不能只检查附着图表。前端事务验收另由 root 负责。

## owned cascade 下一最小方案（尚未实施）

固定来源 `xlsx-gateway.ts:1960` 起先用 classifyRemovedSheetRels 取得 drawing 等拥有部件，沿内部 relationship 建立闭包并纳入每个部件的 .rels。再枚举所有存续 .rels，将仍被存续 owner 引用的闭包 target 拉回保留集，并递归保留其子树，这是共享 media/chart/style 防误删的必要步骤。后续依赖检查跳过确定随表删除的 chart，最后删除闭包并清理 Content Types。不能只删 drawing/chart 路径或忽略共享入边。

本地缺少该图规划，仍拒绝拥有 drawing 的工作表。需独立移植关系分类、闭包、存续入边与保留传播、Content Types 清理，并验证共享 image/chart、external relationship、unsupported part、被删图与存续图引用的区别。当前安全拒绝只是未实现状态，不算来源对齐。

## 前端最小预检实现

新增`assertChartSheetRemoval(workbook,subUnitId,sourceForSheet)`，source callback必须返回实际包按owner关系解析的`readonly {path,xml}[]`，来源缺失或解析不完整须抛错，不能把空live图表列表当成授权。helper仅请求存续工作表的图表来源，跳过被删表自身；这不代表owned drawing/chart级联已完成。

图表公式复用engine的`readChartFormulas`，按chart namespace URI解析合法默认/别名前缀，不依赖`c:f`字面量。前端逐公式按确切runtime unitId归一，再用共享`formulaReferencesSheet`判断，保留字符串、外部簿与unitId大小写身份边界。可信source在root既有removalPreflight callback内调用，确保官方collector和基础删除之前拒绝；不额外扩展collector参数。

只读确认main不存在图表独立交互编辑/删除命令；sync仅将投影chart交给render store，session-core的editCharts/addCharts属于文件操作后重新加载路径。因此本轮不设计live图覆盖旧source的例外，来源须随实际文件加载和基线重放更新。未来若新增live图编辑或删除，必须先建立来源更新/持久化能力，不能直接忽略实际chart XML。

helper缺失RED `/tmp/workbook-chart-sheet-removal-helper-red.log`；实现后helper9项与trusted callback-before-original collector1项合计10GREEN（`/tmp/workbook-chart-sheet-removal-helper-green.log`）。覆盖bare/quoted case/本簿限定符依赖、字符串/外簿/不同大小写unitId允许、跳过target owner、不完整来源抛错及actual图引用在original调用前拒绝。namespace细节和真实ZIP删除契约另由engine独立验证，未重复旧完整套件。

开发态探针新增`CHART_REMOVAL_REFERENCE=Other`允许对照：仅删除无chart依赖的Source，检查history/draft/Python/rev2及存续chart、worksheet、styles真实字节保真。纯UI静态脚本`smoke/workbook-chart-sheet-removal-built-smoke.mjs`已准备，默认拒绝路径与同env允许保存路径均不访问runtime或dev route；等待root实际source接入与统一构建后验收。HTTP context/save/revision由probe提供，文件处理为真实Python，不宣称生产HTTP端到端或live图表编辑解除依赖已支持。

## 真实开发态验收

root实际OPC图来源接入后，默认namespace图表引用Source的拒绝路径`/tmp/workbook-chart-sheet-removal-dev-refusal-green.log`（session7349 exit0）：deleted=false，Source/Other保持，完整snapshot深比较相同，undo/redo=false，localStorage草稿不变，明确反馈Other及`xl/charts/chart1.xml`引用Source，pageErrors=[]。

`CHART_REMOVAL_REFERENCE=Other`安全对照`/tmp/workbook-chart-sheet-removal-dev-safe-save-green.log`（session72615 exit0）：图表存续于Other且仅引用Other，允许删除无关Source；undo/redo、等待草稿持久化及重载、真实Python保存和修订2重开通过。保存仅applySheetEdits删除Source；Other worksheet、chart1.xml、styles.xml字节全部保持，B1:B5=[1,2,3,4,5]，pageErrors=[]。允许路径日志仍观察undo完整snapshot不相等，未定位字段，不把历史成功泛称为全snapshot字节还原；本轮要求拒绝时原子保留的路径完整snapshot相等。

## 最终静态产物验收

最终统一构建`/tmp/office-chart-cjk-caladea-final-build.log` exit0、40.68s，final-budget与contract均exit0，main240.9KiB，未提高cap。自然拆分XML parser与图表引用chunk后，严格使用该批静态产物完成两条纯UI验收：

- 默认namespace图表引用Source：`node smoke/workbook-chart-sheet-removal-built-smoke.mjs`，session4782 exit0，`/tmp/workbook-chart-sheet-removal-built-refusal-final.log`。真标签删除/确定被拒绝，File undo/redo保持Source，草稿/saveLabel原状；114个JS实际HTTP200且SHA与磁盘一致。
- 其他表图表仅引用Other：`CHART_REMOVAL_REFERENCE=Other node smoke/workbook-chart-sheet-removal-built-smoke.mjs`，session30530 exit0，`/tmp/workbook-chart-sheet-removal-built-safe-save-final.log`。删除/undo/redo、草稿重载、Python保存及修订2重开通过；仅applySheetEdits，存续chart/worksheet/styles字节保真，342个JS实际HTTP200/SHA一致。

两路径pageErrors=[]，无TDZ。共同身份：main`BnjejPFA`、XML parser`CSnIWqZm`、engine`HRFOVe0o`、structure followers`iLMhKLk0`、chart references`DySJZa2v`。此验收关闭本轮图表引用删表原子预检及无关删表保真边界；不宣称工作表改名后的默认namespace图表重写、owned chart/drawing级联或live图表清除依赖已完成。
