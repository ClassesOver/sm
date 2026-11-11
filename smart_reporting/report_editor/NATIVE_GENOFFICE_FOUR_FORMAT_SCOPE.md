# 四格式 GenOffice 对齐范围与执行索引

更新：2026-11-11。用户目标：**Word、XLSX、PPTX、PDF 对齐 GenOffice，包括功能区、中文功能区、图标，AI 功能也对齐，AI agent 替换为 Agno 驱动。** 原先Word/XLSX专项只是该完整目标的子集。当前未完成，不给未经穷尽盘点的完成百分比。

固定参考源 `/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。应用分支code本轮已快进17提交至 `9f2c4944`；保留全部本地未提交改动。历史验收代表各自冻结构建，不能自动证明快进后的整个产品。

## 验收要求

1. 四种格式的源真实入口、回调、底层读写及失败边界逐项对应；不能以按钮存在、永久禁用、保留对象或hash替代功能闭环。源自身只会话或没有持久化的功能另记源边界，不静默从完整目标删除。
2. 常规及上下文功能区中文标签、组名、帮助、弹窗和无障碍名称一致，具有相应图标；复用源图标/既有图标库，不把 rb-icon CSS 类名当实际图标证据。
3. AI逐源能力覆盖选择上下文、工具/任务、流式进度与取消、建议预览/采纳/拒绝、Undo及草稿/保存。保留业务权限和文件身份校验，驱动复用现有Agno框架。仅已有一个Agno规划器不等于整套源AI功能已对齐。
4. 有效修改经真实界面、草稿恢复、原生保存、实际下载和明确新修订重开；独立文件回读与视觉核验按功能需求执行。真实模型任务需另有实际调用证据，模拟planner不计真实模型验证。适用的发布非阻断契约保持。

## 当前有源码证据的重点缺口（非穷尽）

以下为当前状态；后文按阶段记录的“未实现／待构建”是历史，不覆盖本表。新增源码尚未构建时，不借上轮静态资产声称本轮浏览器已通过。

| 范围 | 已核实状态 | 下一步 |
| --- | --- | --- |
| Word/XLSX完整功能 | Word 根批注新建与 XLSX 透视表创建/编辑新增真实闭环；e13de64 冻结构建已验取消、历史/恢复、保存下载及新修订重开，并独立 ZIP/lxml/openpyxl 回读。此前批注纯文字编辑、分类汇总、高级筛选及只读表身份保护继续保留。见 [当前缺口](NATIVE_WORD_XLSX_CURRENT_GAPS.md)、[根批注验收](NATIVE_WORD_NEW_COMMENT_ACCEPTANCE.md)、[透视表验收](frontend/WORKBOOK_PIVOT.md)。 | Word 批注回复/删除/解决、复杂锚点/嵌套表；XLSX 完整透视报告筛选/分组/计算字段与源完整工具面仍需逐项闭环。 |
| PPTX功能区中文 | 上轮最终浏览器已核验中文和 96 个命令按钮各具真实 SVG。当前新增六类内建布局中文显示，保持布局 ID/value 及来源自定义对象名；专项与final3严格布局交互浏览器已通过，final4实际入口及相同slides-main原始字节补验通过。 | 新版式下拉、右侧显示及双向立即同步已验收；继续检查未盘点弹窗、媒体与源完整工具面。 |
| 功能区图标 | Word/XLSX/PPTX/PDF 已有中文及图标专项、真实 DOM 与部分浏览器证据；不能以源码 icon 类名代替渲染结果，也没有全源穷尽证明。 | 保持真实图标并逐剩余入口核验功能回调，禁用占位不计功能交付。 |
| PDF AI入口 | 原四个只读 Agno 入口及草稿阅读保留；新增逐根批注改文+AI回复/澄清/跳过、中文SVG面板、完整草稿候选与显式采纳。真实模型9.15秒已验700与AI作者；e2fadd冻结五场景浏览器通过；最后829584 CSS修复构建的实际用户“校验当前修改”已显示700、两项执行、确认框未选且面板可滚动无重叠。真实HTTP/ScriptedModel浏览器与真实provider分层，见 [处理批注验收](NATIVE_PDF_REVIEW_AI_ACCEPTANCE.md)。 | 未保存新增便签的可信append映射与Agno改文回复已新增实际UI/四项执行/精确第二新根IRT验证，见 [草稿便签验收](NATIVE_PDF_REVIEW_PENDING_ACCEPTANCE.md)；合并/拆分页映射、复杂原位重排、全部源AI工具与流式进度仍缺；本增量不等于PDF AI全部完成。 |
| PPTX原生上下文AI | 已接专属原生会话路由，现有文字/几何、整稿页序和商务主题经真实引擎候选预览、显式采纳及同一 UndoRedo/保存链。/tmp/pptx-native-ai-verified-20261111/evidence.json 为 ok:true，含新修订下载独立回读；planner 为确定性替身。 | 合成单对象真实 provider 候选/引擎/显式采纳与独立回读已通过；完整源工具/任务流式进度和媒体 AI 仍缺，现有对象候选不等于全部工具。 |
| XLSX原生上下文AI | 当前新增专属 Agno 服务与路由、范围/整簿明确授权、候选预览和采纳宿主；app 工厂/路由/关闭钩子及 aiEnabled 开关已接，真实装配与权限专项 4 项 RED→GREEN。 | 真实 provider 的 writeValue 字段歧义已按明确布尔合同修复并真实复验通过，显式采纳后 openpyxl 回读正确；最终9f184c1e构建严格浏览器已通过：人工base、过期拒绝、采纳、取消、UndoRedo、新修订2、实际下载openpyxl回读、127实际JS身份与pageErrors=[]。浏览器HTTP/planner仍为明确标记夹具，与真实router及provider专项分层。范围受限结构化候选不等于固定源完整 AI 工具。 |
| Agno已有基础 | 复用既有 ReportingStructuredOutputExecutor 与 create_reporting_generator_agent；新 PDF reader 使用四个来源绑定只读工具，已修复 PDF 模型结构化协议协商，已修复 XLSX 候选字段语义并完成受限真实模型候选复验；真实范围见 [Provider 验收](NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md)。 | 统一生产配置语义，保留每任务工具/模型隔离；继续源完整 tools/stream/session 核实，不宣称 AI 全对齐。 |

源功能和四格式全量inventory、生产权限、桌面等效与真实AI调用目前均未全部核验。此文档确定完整范围和证据门槛，不将未实现事项包装成方案完成。详细后续按一缺口一子agent，最多3个子agent并行（当前环境共4活动槽含root），共享文件编辑分区，root集成及最终核对。不重复完整测试，不提交/推送/部署。

## 2026-11-11 本轮验证补充

- XLSX 高级筛选的 14 个主视图向量已分批通过，仍待 built-browser 验收；不能据此关闭完整筛选专项。`workbook-filters.ts` 的 pinned Univer 自定义条件 tuple 类型已修复；来源读取器 `filter-read.ts` 对超过两个条件设置只读，因此转换保持源的一至两个条件约束。
- `/tmp/four-format-build-20261111.log` 对应 `npm run build` 实际退出 0，包含 TypeScript 检查和 Vite 构建。预算及预算契约在同一冻结构建运行通过，日志分别为 `/tmp/four-format-budget-20261111.log`、`/tmp/four-format-budget-contract-20261111.log`。后续源码变更不能自动沿用该构建证据。
- XLSX Page Layout 旧测试仍寻找已替换的禁用 `scale`，已改为在明确有选区的状态下验证实际 `print-scale-open` 可点击并分发命令；仅该条定向回归通过，见 `/tmp/workbook-page-layout-ribbon-final.log`。

## PDF AI 源语义核实（初始调查，后续实施见当前状态）

固定源 `apps/pdf/src/renderer/App.tsx` 的 Home 总结/要点会按 `aiSelection` 选择整文或选区提示，再经 `runAiPreset` 打开同一个 AI 面板；Annotate 的总结审阅同样走该面板，处理批注仅在可编辑时可用。`i18n/strings.ts` 的中文提示及 `ai/pdf-skill.ts` 明确两种审阅行为：总结必须读取全部批注并按页/主题报告、保持只读；处理批注必须逐条定位原文，执行请求的修改后以 AI 身份回复，歧义时询问、跳过纯讨论和 AI 自身批注。不能将二者合并为单次选中文字改写。

源 `ai/tools.ts` 实际声明 `read_pages`、`search_text`、`read_annotations`、`add_note`、`reply_note`、`edit_note` 等工具，并有原位文字/图片/表单、页面和新文档工具。当前本地 `native_ai_api.py::NativeAIStartPayload` 强制非空 selection，`native_ai.py::NativeAIProposal` 强制至少一个编辑 operation；该合同不能表示只读整文总结或批注总结。下一步须复用 Agno 实现可返回只读回答、带页码引用的任务合同和上下文读取，再接入口；不能伪造空修改来绕过现有选区编辑合同。编辑类任务继续经已有候选预览、身份校验及采纳链路，不复用总结结果直接写文件。以上是源码调查证据，不是真实模型调用或功能验收。

## 后续修复证据（待最终构建）

筛选条件修改后Undo残留outline草稿已用真实Univer/main复现并修复：可承载source-filter数据区由workbookFilterOperations写回可见性，outline层级/折叠仍写入但省略冲突raw hidden。6项main回归与14项outline测试通过，覆盖清条件、源缓存隐藏、人工隐藏+group、新建live filter的原始outline写回；严格built smoke尚待新构建。Word已有批注Node/Python薄桥、真实发布下载/验收失败非阻断/幂等回归均通过，纯前端intent模块10项通过；前端main/controller接线中，仍不关闭批注产品缺口。

## 最终构建与真实运行时补充

最终构建日志 /tmp/four-format-build-final3-20261111.log、预算 /tmp/four-format-budget-final3-20261111.log、预算契约 /tmp/four-format-budget-contract-final3-20261111.log 对应同一命令链实际退出0。Word vendor图标独立分包，render为697.1KiB，不提高原710KiB门槛。包含PPTX中文/61按钮图标、Word批注main/controller与显式放弃重载/打开滚动聚焦、XLSX筛选与outline差分及Undo空草稿状态修复。最终Word/XLSX严格浏览器验收分别在独立端口运行，未以早前构建代替。

实际仓库 doc_engine 已执行 npm run bundle:bridges（/tmp/doc-engine-comment-bundle-20261111.log，exit0），并使用默认Python inspect_docx/patch_docx路径直接验证当前dist：中文emoji批注写入，仅word/comments.xml发生变化；不再仅依赖隔离临时bundle。完整批注族的新建/回复/删除/解决、真实FastAPI授权会话与完整四格式AI仍未完成。

## final3 浏览器验收结果

冻结manifest SHA184c94a96f863198c30ffcfaae1ec2169a8e6b6df2eaca50415bbd62538eada5。Word /tmp/docx-comment-gui-GliBSX/result.json：真实生产DOC引擎、122加载JS逐个SHA、errors=[]，改既有批注文字→UndoRedo→刷新→未blur保存→下载→明确新修订；仅comments.xml变更、旧source拒绝、面板无辅助滚动即可见且焦点/顶部保存可用。只关闭“已有可授权批注纯文字编辑”这一范围，完整批注族仍未实现，HTTP授权路由为替身。

XLSX /tmp/xlsx-advanced-filter-built-20261111-final-03/summary.json：ok=true、saveCount=3、resourceCount=126、errors=[]。三场景实际保存下载并ZIP CRC/lxml/openpyxl独立回读；新修订已保存/身份/空草稿成立。改条件→Undo空操作且已保存→Redo恢复同一草稿且未保存→最终Undo还原均严格通过，复制值也在实际await读取后精确一致。不删除前两版失败历史；clipboard原问题为smoke对async waitForFunction的错误使用，已修测试等待，不以放宽断言冒充产品修复。只关闭单列1–2条件AND/OR的明确高级筛选范围，不扩大成Excel所有高级筛选。

PPTX中文与按钮图标已进同一最终构建，26项DOM测试通过；完整PPTX浏览器视觉/宿主及AI仍待继续。PDF完整Agno任务/工具对齐仍未实现，详见NATIVE_PDF_AI_AGNO_ALIGNMENT_PLAN.md。目标保持四格式完整功能区中文/图标/功能及Agno AI，不以本轮三个专项替代完整目标；未提交/推送/部署。


## 2026-11-11 草稿阅读与原生 AI 集成增量

当前最终统一静态资源 manifest 为 9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba；/tmp/four-format-ai-draft-build-final4-20261111.log（41.40秒）、budget-final4、budget-contract-final4 三个命令均实际退出0。既有 chunk-size/circular chunk 警告未伪装为零告警。该构建包含 PDF 草稿投影提示与nullable引用、XLSX AI 宿主及异步采纳卸载保护、PPTX 标准布局中文及右侧/功能区当前值双向同步。XLSX最终严格浏览器、PPTX/PDF最终入口与资产连续性均已通过，精确分层范围见末尾，不用早期构建替代新构建入口。

- 原生 XLSX app 工厂、专属路由、关闭钩子与 AI/office 双权限开关：新专项先2失败/2通过，再4通过，日志 /tmp/workbook-ai-registration-{red,green}-20261111.log。
- PDF 草稿面板投影身份、实际有效页码、真实跳过原因、原始页导航与新增页无原始ID禁用：新增界面回归先失败再通过，并与受影响原面板共6项通过，日志 /tmp/pdf-assistant-draft-{red,green}-20261111.log。后端18项增量、空草稿6项窄回归及9ee冻结构建四草稿严格浏览器，见 NATIVE_PDF_AI_READ_ACCEPTANCE.md；最终构建入口另补最小资产/浏览器验证，不将旧manifest改写为新整套验收。
- 共享取消竞态：原 cancel_edit 等待依赖后才标 cancelled；真实依赖吞 CancelledError 时会继续调用模型或发布候选。改为先登记终态/清候选，再取消等待；NativeAIService/PPTX/XLSX 每个生成阶段的 await 和异常出口均保留终态守卫。PPTX 新6项先失败后通过，连原相关取消共9通过；Word 新2项先失败后通过，连相关原取消共5通过，分别见 /tmp/native-slides-cancel-terminal-{red,green}-20261111.log、/tmp/native-ai-cancel-terminal-{red,green}-20261111.log。
- 独立只读审阅随后发现关闭钩子 aclose 也会继承同类问题。新增 PPTX/XLSX × 吞取消返回/转异常 共4例先全部失败，再以先标终态/清候选/取消/等待的最小修复全部通过，且验证关闭后不可 accept；见 /tmp/native-ai-shutdown-terminal-{red,green}-20261111.log。没有为此添加发布门禁或改变签发链。
- 四格式受限真实模型调用分开记录在 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md。合成来源、作用域内存仓储与非生产DB边界保留，不把单次成功外推为完整 GenOffice AI 工具、真实部署或复杂文件全覆盖。

本轮没有重复完整测试、提交、推送或部署。完整目标仍未完成。


### final4 最终浏览器与独立审阅

最终磁盘manifest仍为9f184c1e8d6a2d8f94de6d61e0a368db19d9cad4141c0d6b0d065567b3e8b9ba，root独立复读三份最终摘要、源/下载文件SHA和XLSX内容后确认一致。

- XLSX：/tmp/xlsx-native-ai-verified-20261111/evidence.json 为 ok:true，127个实际JS身份、新修订2、明确采纳1次/取消2次、完整base过期拒绝、UndoRedo、实际下载及openpyxl独立回读通过，pageErrors=[]。source.xlsx A1为alpha/bold=true/italic=false；downloaded.xlsx为AI候选标题/bold=false/italic=true，SHA分别为78ac74b9473eb9a85a00052d19fbcbbe98090b740148f92ce521b662f069d7b4、80823d3d37dbe4f7f9527e7c3eb3e6ddfd2907b0edec10483f4daa2d60690a0f。浏览器使用route/planner夹具；真实router/生产model分别另验，不能拼接成生产DB端到端证明。
- XLSX运行时真实缺陷：初次采纳/Undo/Redo各捕获getUnitId空引用。源堆栈证实旧FWorkbook选择订阅在disposeUnit瞬间仍访问已移除unit；修复仅将旧selectionListener.dispose/清引用移到loadWorkbookData前，随后对新unit正常订阅。顺序回归先RED后GREEN，严格browser最终零pageerror，不吞异常或放宽断言。初轮脚本等待不足及后轮真实异常日志均保留；前两轮未在最后断言前落盘原生文件，不伪称有其下载字节证据。详情见WORKBOOK_NATIVE_AI.md。
- PPTX：/tmp/pptx-layout-locales-built-final3-03-20261111/evidence.json 覆盖标准布局中文、自定义源名、原ID/路径、新建草稿、当前版式双向立即同步、96按钮真实SVG，108个实际JS响应核对且错误为空。final4 /tmp/pptx-layout-entry-built-final4-20261111/evidence.json 只补真实入口与初始布局、对象名及108JS身份；slides-main原字节SHA与final3完全相同。不将final4入口补验称为再次完整布局交互测试。
- PDF：9ee冻结构建四草稿严格浏览器、f76冻结构建一次总结分别保留原有范围；final4 /tmp/pdf-ai-final4-entry-only-20261111/summary.json 仅真实入口/四中文SVG控件与21实际JS资源，无AI请求。18模块原字节相同，另3模块只生成导入名变化，按manifest映射替回后精确还原f76字节，非等价列表为空。没有把raw SHA变化说成不变，也没有重复完整四场景/provider测试。
- 独立只读代码审阅覆盖本轮共享取消/关闭、XLSX路由授权、完整base快照、PDFnullable引用与旧任务守卫。唯一发现的关闭P2已以4例RED→GREEN修复，原审阅agent复核关闭；不扩张到本轮未审阅的其它既有工作区差异。root另目视PPTX自定义版式和PDF新增页截图、独立回读XLSX最终产物。

以上仅关闭本轮明确子能力；Word复杂审阅/批注族、复杂嵌套表、四格式完整源AI工具与流式任务、媒体/表单及真实部署等仍待继续，不给未经全量盘点的完成百分比。未提交、推送或部署。

## 本批根批注、透视表与 PDF 审阅增量（2026-11-11）

- Word 根批注：e13de64 冻结构建的完整新建/取消/历史/恢复/未失焦保存/下载/修订2重开通过；root独立回读两条新范围均为chor t、旧批注ID1保留，新ID0/2不碰撞，修改部件仅document.xml/comments.xml。来源与下载SHA均与证据相符，root目视修订2截图。真实HTTP授权与验收失败仍签发下载另有专项，不拼接为生产DB整链。
- XLSX 透视表：e13de64完整交互证据 /tmp/workbook-pivot-built-final-20261111/evidence.json；root独立openpyxl回读真实pivot名称、average/count/max/min、4条cache records、grand average25与手工A1 bold保留，source/download SHA均吻合，root目视中文多值编辑对话框。新实现复用既有xlsx-engine，未造静态汇总替代。
- 独立回读实际修复：透视表average不能写成avg；跨表目标原XML无xmlns:r时必须绑定r；普通无扩展导入透视表重布局须走真实rebuild并清除旧输出尾部。Word跨内部普通空段的精确选区补齐，不以整段降级。PDF原位改字会规范字典键/浮点/字符串转义，需来源精确hash+ref及有界完整引用对象语义比较后重绑，不能放宽为按文字匹配。
- 首统一构建工作簿主包254.9KiB超250KiB预算，透视表改为首次命令懒加载，未调预算。e13de64成功构建39.53秒；随后PDF首浏览器发现旧客户端reply混合守卫及面板重叠，精确修复并保留失败证据。最新统一构建40.06秒、budget/contract均exit0，manifest为e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa。已有模块指令/circular/大chunk等warning仍保留，不称零告警。
- Word final2仅入口补验 /tmp/word-comment-create-entry-final2-20261111/evidence.json：122实际JS身份、中文双入口与源IconComment真实path、无编辑/save/export、错误空；docx-main原字节未变。XLSX final2仅入口补验 /tmp/workbook-pivot-entry-final2-20261111-observed/evidence.json：中文双入口真SVG、动态透视表chunk原字节未变、打开后取消、draft与写请求为空。两者不冒充最终构建重复完整交互。
- root精确连续性 /tmp/four-format-review-build-continuity-20261111.json：Word实际122JS中120原字节相同、2仅生成导入名变化；XLSX128中126原字节相同、2仅生成导入名变化。规范化只将旧/新manifest中的生成资源名映射回唯一稳定模块身份，之后整段脚本精确相等，非等价列表均空；worker依据旧浏览器实际SHA与最终磁盘字节精确相等验证。原始SHA变化不说成不变。
- 新增PDF真实模型任务deepseek-v4.1-flash 9.15秒完成，真实service/Agno/实际预览/显式accept后独立pypdf读回700及AI作者，源与未选择文字不变。合成来源/隔离内存仓储、一次中间解析warning及实际桥版本边界见 NATIVE_OFFICE_AI_PROVIDER_ACCEPTANCE.md。最终修复构建的新增浏览器结果待专属验收追加，不以provider局部成功冒充完整工具面。

此阶段只关闭明确验收的子能力；未保存新增PDF便签的AI处理、复杂Word锚点/回复/解决/删除、复杂嵌套表、完整透视报告筛选/计算字段、四格式完整AI工具/流式任务、未盘点的媒体/表单及完整源功能仍未完成。没有重跑完整项目suite，没有提交、推送或部署。

### 本批最终状态：829584 构建

最终磁盘manifest SHA为82958436439e2cf17b4035f8a60378a29d459e927ff32b87d4998bfd2735cbb9。最后CSS-only构建40.23秒，budget及budget contract均exit0；没有改阈值。Word桥abe54d7c7306eb05a136e6b8caf7255f80e870ee3eee88fa154fb7245b30fd71、PDF桥e423546f4e0ac84d9184e8fe48487b43fb7da769d339e510865330647aa1c711、工作簿桥495c7e78a27805067b8de2ec967db8546190be9e47c436bc81c4347a229ff7b0均核对。

- PDF完整五场景权威结果 /tmp/pdf-ai-review-built-final2c-20261111/summary.json，冻结e2fadd：normal/overflow/clarify/discussion/cancel均通过，21实际JS身份、跨DOM容器不重叠/滚动、源不变及零save/export；实际是Agno ScriptedModel，不能冒充provider。中间一轮helper因合法304响应和缓存假设退出，仅禁用浏览器缓存修正helper，保留失败目录，没有据此改产品。
- 额外真实用户预览发现：在e2fadd中两条执行清单新增108px，画布/确认功能已通过但flex:none面板溢出。仅让新review面板flex:0 1 auto、min-height:0，保留45vh上限/overflow:auto。最终 /tmp/pdf-ai-review-normal-ui-preview-final3-20261111/summary.json 为ok:true：实际点击“校验当前修改”，preview及preview.pdf HTTP200、operations逐字与草稿相同、返回PDF身份相符、PDFjs textLayer含700无500、两个执行条目、确认框初始未选。面板387px、scrollHeight613、实际滚动227，bottom与后方AI面板top均1039；21实际JS、page/console/HTTP错误空，源不变、零save/export。root独立复读摘要并目视实际700截图。
- 版本连续性 /tmp/pdf-ai-review-build-continuity-final3-20261111.json：e2fadd五场景21JS到最终829584中18原字节相同、3仅生成导入名变化，规范化后全文精确相等，非等价为空。没有把final3窄用户预览称为重跑完整五场景。
- Word/XLSX到最终829584连续性 /tmp/four-format-review-build-continuity-final3-20261111.json：实际122/128JS分别120/126原字节相同，各2仅生成导入名变化，规范化后全文精确相等。完整交互仍对应e13de64，真实入口补验对应e2fadd，最终CSS-only构建靠明确资源连续性衔接，不冒称全部场景重新运行。

本阶段新增能力已达到上述限定验收面；原始四格式完整目标仍未完成，当前缺口表继续有效。没有重复完整项目suite、提交、推送或部署。


## 2026-11-11 回复、待保存便签与隐藏页本批收尾

最终统一前端 manifest 为 7536053f7c47638639d26d3f4ac63285b33cd05f64fdb7d7a82229106710696d。/tmp/four-format-reply-pending-hidden-build-final4-20261111.log（Vite 40.92秒）、budget-final4、budget-contract-final4 同一命令链实际 exit0；保留既有 chunk/circular/module 注释警告，没有提高预算或声称零构建警告。未运行完整项目测试，未提交、推送或部署。

- Word 既有根线程文字回复已接真实 OOXML 父关联及同一草稿/历史/恢复/未失焦保存；完整保存下载与修订2仍对应8c3和独立真实HTTP非阻断证据。971b补验锁解除状态提示；独立审阅随后确定多根A空输入切B会把回复错误提交给A，单行修复同步重绑target与当前snapshot，7项控制器回归通过。final4仅运行新增多根切换窄浏览器：122实际JS，PM/草稿精确B、A无新增、UndoRedo与非空拒绝保全、错误全空、零save/export/patch。root独立复读并目视两截图；具体见 NATIVE_WORD_COMMENT_REPLY_ACCEPTANCE.md。不把旧单根保存链说成已在新构建重跑。
- PDF 未保存新增便签可由Agno在完整base绑定下改字并回复，按实际引擎append回执的operationIndex/localId/PDFRef定位，含同外观双根精确归属。8c3窄浏览器实际21JS、正常预览700、四项已执行及未选确认框、真实新增回复25R精确指第二根23R，源与base保全，零save/export；使用真实Agno加ScriptedModel，不能称为本轮真实provider。独立只读审阅未发现指定映射范围的确定缺陷，未动态注入采纳中并发取消/过期。见 NATIVE_PDF_REVIEW_PENDING_ACCEPTANCE.md。
- XLSX 修复table relationships未完整登记tableParts时错误发布不完整owner快照；无完整身份不允许误删依赖。8c3两真实文件官方右键删除路径实际拒绝并给具体原因，两个sheet/草稿/保存状态保留、零mutation和页面错误，每例127JS。只关闭本次关系完整性边界，不重复既有完整删除链。见 NATIVE_XLSX_TABLE_OWNER_COMPLETENESS.md。
- PPTX 隐藏/取消隐藏复用原引擎属性及原页身份，中文真SVG/当前状态、UndoRedo/恢复/重排/保存下载与修订2已在971b完整浏览器通过（108JS、96按钮图标审计）。独立文件回读确认输出hidden=[false,true]且只改允许XML；另修合法show=false及单双引号兼容、复制预隐藏页状态。root目视发现标签竖排后仅改两行CSS；624aae只读重开窄补验确认标签33×16单行、标题和四按钮不被覆盖、零错误/草稿/save/export。root独立实读和目视，见 NATIVE_PPTX_HIDDEN_SLIDES_ACCEPTANCE.md。

最终资源连续性不冒充重跑：/tmp/four-format-reply-pending-hidden-continuity-final4-20261111.json 比较8c3实际浏览器资源与final4，PDF21和XLSX127无真实代码差异，Word122仅docx-main含明确状态/切根修复；/tmp/four-format-reply-pending-hidden-971-to-final4-20261111.json 比较971b，PPTX108无真实代码差异、Word仅docx-main含切根修复。生成导入文件名仅按manifest唯一稳定身份规范化后全文精确比较，未将raw SHA变化说成字节相同。/tmp/four-format-reply-pending-hidden-css-bridges-final4-20261111.json 另确认624aae实际加载6份CSS与final4逐字节相同，DOC/PDF/PPTX三个bridge身份不变。各完整/窄流程保留自己的原manifest与边界。

完整目标仍未完成：Word复杂嵌套表/完整审阅及其它未迁移功能族，XLSX剩余透视/图表/打印/导入能力，PPTX放映/媒体/审阅接线，以及四格式完整AI工具与stream仍需逐项对齐。新增限定源码盘点 NATIVE_PPTX_COMMENTS_SOURCE_INVENTORY.md：固定源经典批注查看/根新增/逐条删除已有实际保存链，本地引擎同源但桥与宿主尚未接；源未实现的回复/解决不误报为本地漏接。该调查不是产品交付，不据此给总完成百分比。

2026-11-11 XLSX 并行增量：CSV 导入当前选区及打印显式四边边框已分别完成冻结构建真实浏览器验收（各129实际JS身份、errors=[]），CSV包含一次保存下载/openpyxl独立回读与修订2重开，打印包含真实File→Print的HTML、截图与1页A4 PDF。详见 ../../docs/parity/2026-11-11-workbook-csv-import.md 与 NATIVE_XLSX_PRINT_RENDERING_ACCEPTANCE.md。最终 npm run build、check:budget、test:budget 通过；主入口246.6KiB低于250KiB。图表只完成Matplotlib生成及单张图片创建/替换真实文件探针，可信资产与宿主入口未交付，见 NATIVE_XLSX_STATIC_CHART_ALIGNMENT_INVESTIGATION.md。完整图表、PrintDialog、连接与其余功能族继续保留缺口。

后续共享构建连续性核对：浏览器专项完成后，共享 static 又被其它工作重建。root 实读本专项下载 XLSX，并比对两份浏览器资源清单：各125/129资源字节未变；4份共享宿主资源发生变化，不能称当前整包重新通过同一专项。workbook-main、CSV独立chunk及print-settings实际字节未变，见 /tmp/xlsx-parallel-shared-build-continuity-20261111.json。浏览器结论绑定各自原冻结证据；未重复完整测试。

2026-11-11 后续XLSX并行增量：已有文件页眉页脚文字打印、查询与连接只读面板完成真实浏览器专项。打印三页验证first/even/odd、页码/总页数、文件名/表名、转义、0.2in距离与50%字体；查询覆盖真实连接/空态/损坏XML，目标导航保留人工草稿与历史，零保存/零外部请求。各130JS身份由root逐字节核对当前static一致，errors=[]。引擎读取4项、打印35项、上下文6项、查询13项、主入口/Ribbon84项定向通过；最终build/check:budget/test:budget通过，主入口247.6KiB/250KiB。见 NATIVE_XLSX_PRINT_HEADER_FOOTER_ACCEPTANCE.md 与 ../../docs/parity/2026-11-11-workbook-queries.md。页眉页脚编辑/图片、完整PrintDialog、图表创建编辑、外链/合并及其它高级能力保留缺口；固定源查询面板本身不执行查询，refresh-all只刷新透视表。

2026-11-11 再次并行增量：默认/奇数页页眉页脚六区编辑与透视表全部刷新完成。页眉两次真实保存下载重开、清空、first/even/flags及其他ZIP保全，最终布局单独补验；页设置日志不承诺native Undo。透视刷新真实多表导入、增长/收缩、UndoRedo保留源草稿、reload、Python bridge保存、独立openpyxl结果180与修订2重开通过，130JS/errors=[]。本轮按固定GenOffice源码参照，未新增依赖或@sheets-web引用；旧本地包名未全局改名。含公式来源、共享缓存/复杂透视、缺records明确拒绝，不刷新外部连接。前后端产物均已重建；定向52项集成、最终tsc/Vite/check:budget通过，main249.8KiB/250KiB。见NATIVE_XLSX_HEADER_FOOTER_EDITOR_ACCEPTANCE.md和../../docs/parity/2026-11-11-workbook-pivot-refresh.md。完整打印、图表创建编辑、合并工作簿与高级透视仍保留缺口。
