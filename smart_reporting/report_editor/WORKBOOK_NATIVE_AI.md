# XLSX 原生 AI 宿主与能力范围

固定 GenOffice 来源：f8c17004fb730df11f0f743164ffd8b4281bb38c。
核对 apps/sheets/src/renderer/ai/workbook-skill.ts、tools.ts、AiChatPanel.tsx；本地沿用发送时冻结选区、引用范围和同一草稿语义。

## 已接通

- 原生中文 AI 助手和 Lucide SVG 按钮；默认仅当前单元格范围，用户须明确改选整份工作簿。
- 上下文来自真实引擎对完整人工未保存 operations 的预览。选区模式只引用该表该范围内单元格，服务器严格核对范围并拒绝任何范围外编辑及结构操作。选区最多 10000 单元格，模型上下文最多 120000 字符。
- create_native_workbook_ai_service 复用 WorkbookAIProposal、AgnoWorkbookProposalPlanner、ReportingStructuredOutputExecutor 和真实 Agno generator agent；未新增模型协议或解析正文伪工具调用。
- 选区模式支持 applyCellEdits 的值、公式与格式。显式整簿模式开放现有 schema 的12类结构化操作：单元格、工作表、行列、数据验证规则、条件格式规则、批注、透视表新增、列宽、行高、页面设置、大纲、表格新增。候选仍须经过真实 XLSX 引擎预演；无法预演的候选返回失败并保留人工草稿。
- /api/workbook-ai/start、cancel-request、/{id}、/{id}/accept、/{id}/cancel 复用原生 session、同源 CSRF 和 document/revision/scope 绑定，不接受文件路径。
- clientRequestId 在第一次异步调用前生成；服务器先登记后台任务再做预览。提前取消保留一小时墓碑，同身份同内容重试重放，同身份不同内容拒绝。卸载取消使用 keepalive；依赖吞取消后也不可继续调用模型或发布候选。
- 中文差异预览只显示候选，点击采纳后才写入同一 NativeDraft。前后及服务器均核对来源 SHA 和完整操作快照，人工格式等 base 操作保持有序。共享撤销、重做、持久恢复、保存新修订与下载路径。
- 候选不自动保存；业务事实提示为人工复核软提醒。没有改动报告发布或下载的非阻断契约。

## 明确缺口

- 当前实现是受限结构化 workbook planner，并不等价于固定源完整 AgentSkill 工具系统。
- 固定源 get_workbook_context/read_range/aggregate_range/load_guide/read_formats/read_sheet_features/read_cells/find_cells/select_range/trace_precedents/trace_dependents/propose_operations/create_document 的多轮工具执行面未整体移植。
- 没有接通全新文件生成、多轮工具读取、跨来源检索、AI 图表与图片、保护与主题、模型选择或桌面队列。未新增 Plotly、interactiveCharts 或 .plotly.json。
- 差异预览是结构化候选清单，不是独立预览文件下载或截图；采纳后网格以真实 XLSX 引擎结果重新载入。

## 验证

- test_workbook_native_ai.py：范围越权、只引用冻结范围、完整人工草稿过期、HTTP CSRF/版本/严格输入/跨公司隔离、提前取消墓碑、真实 XLSX engine + openpyxl 独立公式和人工值回读。
- 新增三阶段依赖吞取消用例：来源预览、planner、候选预览均不能令取消任务继续或发布。
- workbook-native-ai.test.ts：显式采纳、整份草稿变化拒绝、start 回执前取消与迟到任务清理、采纳前后异步快照期间关闭不得恢复请求/写入、CSRF 和 keepalive、真实 SVG 按钮。
- workbook-native.test.ts：候选进入同一 NativeDraft，人工 base 保留，撤销/重做、保存与下载 URL 贯通。
- 浏览器命令：WORKBOOK_SMOKE_PREVIEW=1 WORKBOOK_RIBBON_CASE=native-ai WORKBOOK_SMOKE_PORT=4198 WORKBOOK_EXPECTED_MANIFEST_SHA256=<root最后manifest> WORKBOOK_SMOKE_EVIDENCE_DIR=<独立目录> node smoke/workbook-ribbon-gui-smoke.mjs。
- 浏览器使用确定性 planner 与 HTTP route fixture，检查 CSRF 请求头但不冒充真实服务授权/真实模型 endpoint；后端 ASGI 用例独立覆盖真实路由授权。XLSX 预演、保存、下载字节与 openpyxl 回读为真实引擎。evidence.json 记录 manifest 与实际加载 JS 文件的 SHA256/字节数。

## 2026-11-11 定向验证记录

- 后端初始4例通过；共享取消终态修复后三阶段依赖吞取消3例通过；真实 writeValue=59 故障增加2例（prompt明确布尔写入标志、引擎继续拒绝数值标志），均先记录失败合同再完成修复。
- 前端专用4例通过，新增异步快照采纳前后关闭2例均 RED→GREEN；同一 NativeDraft 贯通单例在关闭守卫修复后复核通过。既有 workbook-native 文件4例已通过，替身补齐当前 RTL、事件disposer、有效ZIP与表头配置；未放宽生产校验或测试断言。
- 首次 built browser 使用 manifest 9ee998908ab65f7c2ca8f8551b3a67954c9423fccd49d89bce549746bb987141；已走通人工base、过期拒绝、明确采纳与Undo/Redo，但脚本未等待Redo载入解除inert就点击下一任务，取消按钮不可见而失败。日志保留 /tmp/xlsx-native-ai-20261111-attempt1.log。该轮不能计为浏览器验收通过；仅补脚本等待，待最后冻结资产复验。
- 真实 provider 初轮由root捕获 writeValue=59 的字段歧义，生产引擎严格拒绝；修复补充显式布尔语义和合法完整JSON示例，未强转错误类型。独立单格式复验首次因导入路径未启动，随后本地 .env 授权返回403 AccessDenied.Unpurchased 且未产出candidate，结果 /tmp/xlsx-native-ai-provider-20261111.json；不能据此声称真实模型成功，后续须用root已验证授权环境复验。

### 真实模型复验成功

root 使用已验证授权环境，以 PYTHONPATH=. .venv/bin/python 启动仅 XLSX 的生产 factory 探针，2026-11-11 成功。/tmp/xlsx-native-ai-provider-root-20261111.json 记录 deepseek-v4.1-flash、3.87秒、真实 NativeEditorService / AgnoWorkbookProposalPlanner / 引擎预览 / 显式 accept / openpyxl 独立回读。模型实际返回 writeValue=true、cell.value=59；A1 为数值59，B1 保持 Untouched，原始来源字节不变。

来源 SHA256：cd333b726d8e37e2d21de55214cabe5c7c216009423231c29ace9e02953e87c7；采纳后文件 SHA256：310da4d3af3a0314c5247f5b04277c3d96c1a847add0e466e20931fff61933db；产物目录 /tmp/native-office-provider-edits-20261111-i51x80cz。该成功是独立真实provider证据，不来自浏览器确定性路由夹具；此前本地.env的403仅是不同启动授权环境记录，不是产品代码失败。

### 旧选区订阅生命周期回归

最后构建 f76a3d6903e283f50fbffaf9cc28850bd16024d7f09811e4c71242cfe3fbc5ec 的严格 browser 已完成采纳、Undo/Redo、取消、保存新修订和实际下载回读，但零pageerror断言发现三次 getUnitId null，故该轮仍验收失败。日志 /tmp/xlsx-native-ai-20261111-attempt2.log 保留。

一次采纳最小复现的真实堆栈定位到官方 FWorkbook.onSelectionChange：旧订阅在旧unit销毁后才释放，订阅内 getCurrentUnitOfType(...).getUnitId() 遇到空unit。日志 /tmp/xlsx-native-ai-20261111-diagnostic.log、截图 /tmp/xlsx-native-ai-diagnostic-20261111/after-first-accept.png。未修改Univer、未添加catch吞异常、未放宽pageerror断言；workbook-native贯通的生命周期顺序断言先RED（load→dispose→subscribe），修复为旧监听dispose并清引用→load→新监听subscribe。该最小生产变更需要root重新统一构建后再验收。

前两次失败脚本在最后断言之后才写证据，因此没有落盘那两轮的 source.xlsx / downloaded.xlsx 原始字节；不能把日志中的保存payload视为已保留的实际文件，也没有重建替代产物。两轮日志与诊断截图均保留。后续专项将真实来源与下载文件、实际JS身份和截图在最终 pageErrors=[] 断言之前落盘，失败时 evidence.ok=false；严格断言保持不变。

## 最后 verified 浏览器证据（2026-11-11）

- 生命周期修复后的最后 manifest：9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba。root统一 build、budget、budget contract 均 exit0。本专项仅跑 native-ai 模式，未自行重复构建。
- Chromium 140.0.7339.16，严格 smoke exit0，原 pageErrors=[] 断言通过；人工未保存格式引用、候选不自动写入、完整草稿变化拒绝、明确采纳1次、请求取消2次、NativeDraft Undo/Redo、保存修订2和真实下载 fetch/openpyxl回读全部通过。六个AI按钮各有一个 aria-hidden SVG。
- 证据目录 /tmp/xlsx-native-ai-verified-20261111：source.xlsx、downloaded.xlsx、after-edit.png、evidence.json；最后截图已实际目视，中文范围/任务/草稿按钮和网格正常。日志 /tmp/xlsx-native-ai-20261111-attempt3.log。
- 来源 SHA256 78ac74b9473eb9a85a00052d19fbcbbe98090b740148f92ce521b662f069d7b4，下载 SHA256 80823d3d37dbe4f7f9527e7c3eb3e6ddfd2907b0edec10483f4daa2d60690a0f。独立二次openpyxl回读：原A1为alpha/bold=true/italic=false，下载A1为AI候选标题/bold=false/italic=true；来源文件仍保持原值与格式。B列文件列宽30保持不变。
- evidence记录127项实际加载JavaScript身份。lazy-workbook-native-ai-BFiaRots.js：6978字节，SHA256 aead1a2d592eb3fd864441404d51ee2a3712bf5bd81e1501fd0b959e4f09a332；lazy-workbook-main-DQ-le5R9.js：245843字节，SHA256 59954ce1e8c3255162fe20e9085ca6d4f7829ae39f0e8195c4ef807e448dffc3；lazy-native-office-view-D0Fil_nY.js：15192字节，SHA256 40e6a3fc70607b624071e0669242fe33c999480bfa9339f3e79e8c818cb327b6。
- 此轮浏览器认证与planner均明确是HTTP route fixture；真实引擎、下载字节与独立回读不是替身。真实路由/作用域测试及真实provider成功记录见前节和统一 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md，不能混称为浏览器直连真实provider或生产身份系统。
