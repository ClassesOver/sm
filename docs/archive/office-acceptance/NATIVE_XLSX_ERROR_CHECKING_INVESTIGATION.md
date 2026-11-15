# XLSX 公式错误检查：独立只读调查

2026-11-10；固定完整源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。仅新增本文件及 `/tmp/xlsx-error-checking-investigation/`，不改生产/AUDIT，不触发产品build，不运行旧测试。

## 当前明确缺口

审计矩阵 Formulas 行早期写“追踪/监视未实现”，但追加验收和当前代码已接通 trace/watch，不能照抄旧状态。**Error Checking 目前确实未闭环**：`frontend/src/workbook-ribbon.ts:476` 的审核组把 trace、show formulas、watch 绑定 command，error-checking 仍是无 command action；`:1245` 对该按钮设置未接入原因并 disabled。RibbonCommand 无此枚举，workbook-main 无分支，未发现本地错误检查模块或结果导航。已有公式计算/显示公式、定位和监视窗口均不等价于错误检查，不把静态按钮视为支持。

## 固定源入口与实际语义

| 固定源文件 | 事实 | SHA-256 |
| --- | --- | --- |
| `apps/sheets/src/renderer/ExcelShell.tsx:3039` | 点击发送 error-checking | 本次未另算hash，固定ref约束 |
| `apps/sheets/src/renderer/ribbon-actions.ts:719` | 完整载入与lazy分流，完整载入扫描当前表 | `e4effd7feda2b4e9c6f8feb1b7f976b0b6325a80a2e690cb4fd17e46888efa11` |
| `apps/sheets/src/renderer/error-checking.ts` | streamed整簿分页、journal覆盖、跨表next、身份/并发guard | `73b1e0fb40cc76de06e087146d882c1bca17f932aa574d11810928e10e9e6ddf` |
| `apps/sheets/src/renderer/ai/workbook-search.ts:30` | 共享精确error taxonomy、40万cell budget、1.8万batch | `1cc15129da7e2c11fdf47e529d9f0c4f2bd996567742a304a12b5be3771d4416` |

完整载入分支使用 **当前 worksheet.getSheet().getCellMatrix().forValue** 的 cell.v，不是display formatter，不扫描公式文本，也不扫描其它工作表。收集匹配的字符串，按row-major位置找当前选区之后第一个，末尾回绕。执行目标range.activate、手动refreshSelectionFormatRef、官方scroll-to-cell；显示数量、地址、值，零命中明确“无错误”。不改公式、忽略规则、修复错误、强制重算或写XLSX。

源注释说display values，但实际是cell.v；这一区别必须明确。完整载入regex仅包含DIV/0、N/A、NAME、NULL、NUM、REF、VALUE、SPILL、CALC，且没有结尾锚点：真实探针命中 `#REF!suffix`，漏过 `#FIELD!`。不能把该bug固化成未来验收标准。

流式路径仅当lazyState存在且preloadComplete=false：遍历live sheet IDs（包括会话新增，排除已删表），对file meta extent做分页；结构操作用netAxisDelta算screen大小，并交readSheetRangeMapped映射。journal hasValue条目优先覆盖file同位置；style-only不覆盖；journal公式value=null从Univer读取实时结果。共40万扫描cell预算、每批约1.8万；分页读取失败或索引未完整标truncated，不应说完整检查无错误。pickNextError按工作簿sheet顺序/行/列排序，跨表选后续并回绕；跳前ensureLazyRangeLoaded，切表/activate/刷新echo/滚动。模块scanInFlight防重入，lazy state对象变更则停止后续读取/旧目标导航。finally释放inFlight，但runStreamedErrorCheck本身没有catch，fire-and-forget的异常兜底仍需宿主负责。

共享streamed ERROR_VALUE_RE是完整锚定：REF/DIV0/VALUE/NAME/N-A/NUM/NULL/SPILL/CALC/FIELD/CONNECT/BLOCKED/UNKNOWN/GETTING_DATA。它和loaded分支taxonomy不一致；源也不声称语义审查诸如“公式省略相邻单元格”“文本数字”“不一致公式”“忽略此错误”的Excel完整Error Checking规则。本项范围只是发现现有错误结果并导航。

## 可执行源探针与边界

证据：`/tmp/xlsx-error-checking-investigation/probe.mjs`、临时`source.cjs`、`run.log`、`results.json`。执行 `node /tmp/xlsx-error-checking-investigation/probe.mjs` exit0。临时esbuild仅构建探针，不构建产品。

loaded分支从固定ribbon-actions原文按case边界提取执行，正则/COLUMN_LIMIT也从原文提取；streamed scan/pick直接导入固定error-checking.ts，netAxisDelta走真实源模块。只stub翻译、readSheetRangeMapped和ensureLazyRangeLoaded IO边界；共享ERROR_VALUE_RE从原文抽取。fake cell matrix与journal有明确数据，不冒充真实Univer计算栈或完整XLSX读取测试。

实际验证：

- loaded A1=`#REF!`、B3=`#DIV/0!`、A5=`=1/0`（纯文本）、A6=`#FIELD!`、A7=`#REF!suffix`。从A1连点4次得到B3→A7→A1→B3，count3，每次调用官方scroll与echo；纯公式字符串未被当错误，现代FIELD漏掉，suffix误报均真实观察。无错误数据反馈appNoErrorsFound。
- streamed journal先覆盖已修复A1，不让file旧REF复活；公式journal null经resolveFormulaValue得到DIV0；style-only不隐藏file FIELD；新增sheet journal CALC被纳入，已删file sheet s2未读；suffix不命中。结果DIV0/FIELD/CALC三个，未truncated。
- pickNextError从s1末错误跳新增sheet，再回绕s1行最早错误。
- IO失败truncated=true；isStale立即true时0次page read且truncated；30万×4 extent在23批后达到40万预算并truncated。

本轮未执行真实stream sidecar/readSheetRangeMapped、runStreamedErrorCheck完整UI、XLSX parser或公式求值；并发锁/ensure后identity guard为源码核对，未冒称浏览器或真实provider验收。不重跑固定源已有error-checking.test.ts。

## 本地建议与复用边界（未实施）

本地workbook-main以完整currentModel/buildWorkbookData→loadWorkbookData载入现有workbook，未见源lazy sidecar/journal协议。因此首版应明确复用 **完整载入当前表** 的源范围，避免为此引入whole-file streaming服务或自行复制journal。若本地存在未完整导入的sheet，必须报告检查范围受限，不能把当前稀疏snapshot声称完整源文件检查。

1. 独立只读controller扫描官方FWorksheet.getSheet().getCellMatrix().forValue的现有计算结果；稀疏矩阵遍历避免按整张百万行空网格逐格getRange。显式row/column排序再选next，避免依赖内部枚举顺序。扫描不自行求值/解析公式，不强制重算；手动计算模式说明看到的是当前缓存结果。
2. 错误分类应优先复用已安装Univer0.25.1 `@univerjs/engine-formula` ErrorType/ERROR_TYPE_SET，涵盖CYCLE/ERROR等本地公式错误；对源现代FIELD/CONNECT/BLOCKED/UNKNOWN明确补充精确集合并记录差异。**精确匹配**，不复制loaded suffix误报。保留源的literal error字符串也可匹配语义，不强制必须cell.f存在，否则会静默漏源已有cached错误。是否区分文字“#REF!”与typed error属于可见行为设计，不能无测试自行收紧。
3. 导航复用官方getRange().activate、worksheet.scrollToCell和现有createWorkbookReveal（冻结区、RTL、真实viewport、cancel生命周期已封装），刷新现有selection echo/Ribbon/formula bar。不要自己绘制选择框或直接改滚动DOM；别因错误检查修改view/file、markDirty、stage操作、undo历史或发保存请求。
4. Ribbon加真实command，readonly/protected可用；loading/disposed/calculationBusy等期间正确禁用。监视窗口曾暴露saved祖先inert问题，错误检查不新增面板可避免同问题，但若有结果面板必须挂可交互宿主。查无错误、命中数量/地址、检查范围和读取失败要明确反馈，不将失败显示“无错误”。
5. 异步reveal捕获workbook core与sheet core身份并在每个await后核对，切簿/reset/dispose取消；同一controller防重入，多实例独立，避免照抄source module全局锁限制并列宿主。只读结果容错和异常归feedback，不让未处理Promise rejection泄漏。

首版不实现自动修公式、忽略列表、逐条规则向导、跨整簿扫描、lazy分页、外链访问或错误持久化。若后续明确选择全簿，应复用source pickNextError，单独写跨表/sheet membership协议和验收，不静默改变当前表按钮范围。

## 必要验收

新增窄测试验证：真实command不是disabled占位；无错/单错/多错next回绕、已在错误格会跳下一格；精确taxonomy含legacy/现代/Univer本地值，suffix/普通字符串/公式文本拒绝；稀疏远处命中与实际计算结果；错误修复后重新扫描不残留；当前表范围不误报其它表；只读/protected/saved可导航且零mutations/dirty/history/operation/request；未就绪/异常反馈；identity替换/rapid clicks/dispose取消；reveal冻结/RTL不扩scope。

真实built至少一份含`=1/0`、无效引用及不同表错误的XLSX，等待官方计算稳定后连续点查，验证active selection+实际viewport+feedback；保存文件/操作只含用户原有修改，检查本身无变化。不只断言按钮存在，不因本项重跑完整旧测试。
