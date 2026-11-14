# PPTX 拼写检查与翻译预设入口

日期：2026-11-13。固定源 `/home/junge/pros/genoffice-source-full` commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

本专项补齐已确证的两个源 AI 预设入口，复用既有 Agno 原生候选链。未新增 AI agent、后端路由或独立文件写入路径。
这不是 PPTX 全部 AI 工具、四格式全面对齐或所有语言翻译质量验收。

## 源语义与本地接口

- 固定源 `apps/slides/src/renderer/components/Ribbon.tsx:2455–2504` 的拼写检查经 `onAiPreset(ribbonSpellCheckPrompt)`，翻译先选择 `TRANSLATE_TARGETS` 的 21 种语言，再调用同一入口。`App.tsx::pushAiPreset` 打开 AI 面板并登记预设。
- 源 `i18n/ribbon/zh.ts:413–418` 明确区分范围：拼写为“逐页检查这份演示文稿”，翻译为“当前页的所有文本”。因此本地 **拼写检查初始化 deck，翻译初始化 slide**，没有把整稿校对缩成单页，也没有把单页翻译扩成整稿。
- 新 `frontend/src/slides-ai-presets.ts` 保留固定源语言顺序、中文名称和稳定语言 ID。`slidesAIPreset` 只产生预置指令、范围和标题；非法语言拒绝生成预设。
- `mountSlidesNativeAI.openPreset({kind:'spelling'} | {kind:'translate',language})` 先取消旧任务/候选，再填入已有面板。范围和指令可见，**点击“生成候选”才调用 AI**，候选仍须明确采纳。与源 autoRun 的差异是本地主动保留生成前的可见授权确认，不自动消耗模型额度。
- `createSlidesNativeRibbon.setAIEditEnabled` 由实际 nativeAIHost 就绪后回填。未启用 AI、保存或锁定时仍禁用；翻译 select 有真实源 SVG、中文标签和语言名称，选择后复位。
- `slides-main.ts` 仅新增两条预设 action 及一个就绪回填。当前页授权继续由 `slidesAIObjects` 从真实能力清单和最新 NativeDraft 投影，包含未失焦的人工改文、可写表格/安全图表，排除其它页、只读对象与已删除对象；备注不随画布授权。
- 生成、工具进度、独立引擎预览、明确采纳、放弃、取消、UndoRedo、草稿恢复和保存请求均复用现有链。任务期间换语言废弃旧身份；换页/改稿后的单页翻译候选由现有完整快照守卫拒绝。

## RED / GREEN 与定向回归

证据根目录：`/tmp/office-word-pptx-source-gaps-20261113/ai-presets`。

- `red.log`：新增最初 7 项宿主测试得到 **6 失败、1 通过**，实际复现无语言菜单、两个按钮无法打开预设，以及后续候选链无法执行。
- `green.log`：上述 7 项通过。
- `related-tests.log`：预设、已有 AI 面板/取消/客户端、当前草稿投影、Ribbon 与中文枚举共 7 个文件 **69 项通过**；这是当时含 7 项预设的范围，不虚称后续所有测试再次全跑。
- `final-tests.log`：最终预设文件 **10 项通过**，新增迟到 start 回执、旧取消失败与正在采纳/保存的守卫；首个测试还验证候选明确采纳后的 UndoRedo 及原共享保存请求的 source SHA 和 operations。
- `race-tests.log` 中一次失败是测试误用不存在的 `NativeDraft.setSaving`，已改为真实 `beginSave/saveFailed` 生命周期；没有为通过测试添加测试专用生产方法。
- `git diff --check`、Python 夹具 `py_compile` 及 MJS `node --check` 均定向执行。
- 本轮早期只读 tsc 结束时只有 `pdf-view-ribbon.ts:93–94` 的 Event 类型问题；已交 root/PDF agent 处理，不借此宣称全工作区类型通过。后续统一 tsc/build 由 root 负责。

## 真实 HTTP + Agno + 引擎的源码浏览器验证

最终证据：`browser-source-verified/summary.json`，`ok:true`，`errors=[]`、`consoleErrors=[]`、`httpErrors=[]`。

使用新 `frontend/smoke/pptx-ai-presets-smoke.mjs`，复用 `pptx-ai-objects-server.py` 的原生授权 cookie、CSRF、工作区、真实 NativeSlidesAIService 和 AgnoSlidesProposalPlanner。
新增夹具模式 `PPTX_AI_PRESETS_SMOKE=1` 使用双页文字，模型为 **ScriptedModel，经真实 Agno 工具执行**，不是远端真实 provider。
旧表格/图表/备注模式不改变原工具调用身份；新的多页校对脚本先读每个修改页，再提交候选。

真实浏览器已执行：

1. 改第一页文字，不失焦进入翻译；核对 21 种语言顺序、中文标签和真实 SVG。预设打开时没有任何 AI job。
2. 点击生成，真实 HTTP 请求包含最新人工草稿、source SHA 和仅当前页明确对象 selection。工具执行 `get_presentation_context → read_slide → propose_operations`，真实引擎验证候选，候选前后草稿相同。
3. 换日语废弃旧候选，再换英语生成并明确采纳；撤销恢复人工草稿、重做恢复采纳候选。
4. 拼写检查显示整稿范围，实际 deck 请求 `selection=[]`；工具读两页，候选展示第二页“错别自 → 错别字”。放弃后草稿不变。
5. 重新生成单页翻译后切到第二页，采纳被完整快照守卫拒绝；关闭新的校对候选发出取消请求，草稿保留。
6. 对采纳过的翻译候选独立 `python-pptx` 回读：第一页为 `Draft revenue 42, expenses 17.`；第二页仍为原“错别自”；表格 42、图表 `[42,17]`、页序和备注均保持。`translation-candidate.png` 与 `spelling-candidate.png` 已目视检查，真实侧栏中范围、前后差异及采纳/放弃按钮可见。

本层通过真实生产模块的 Vite 源码入口加载，`sourceModuleHashes` 记录五个变更模块身份；**不是冻结生产 bundle 验收**。
复制的旧 manifest 仅为源模式 HTML/图标静态宿主脚手架，不表示该 manifest 的生产 JS 含本次实现。没有在本烟测发起 `/save` 或 `/export`，独立回读的是真实引擎补丁产物，不能称为下载/修订2验收。

此前两次源码夹具失败保留在 `browser-source` 和 `browser-source-final`：前者未先 read_slide(1) 即提交第二页校对，被现有 Agno 工具守卫拒绝；后者试图对已经翻译好的相同文字生成空修改，候选被现有校验拒绝。只修夹具，没有放宽工具或引擎校验。

## 冻结生产构建完整链验证（8d4）

root 完成统一构建后，于本次实际执行同一烟测，未改产品、未重新跑测试集或重复构建：

- 冻结静态目录：`/tmp/office-four-format-source-increment-20261113/static`。
- manifest SHA256：`8d4ca1394b78848aed62e1dbfc80add3b9b629cac8b91683c5d0976ee5cef2b4`；根冻结目录和烟测副本实际摘要一致。
- 最终证据：`/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final/summary.json`，`ok:true`，`layer="real native HTTP + frozen production bundle"`。
- 实际浏览器加载 **129 个 JS**，逐个响应字节 SHA256 与冻结副本匹配；完成后 manifest 未变化。`errors`、`consoleErrors`、`httpErrors` 均为空。
- 同一次冻结浏览器实际完成上述翻译预设、最新草稿引用、英语候选生成/明确采纳、UndoRedo、整稿拼写候选、放弃、语言切换、换页拒绝过期候选和关闭取消。两张最终 `translation-candidate.png` / `spelling-candidate.png` 已目视：当前页/整稿授权范围、候选前后差异、真 SVG、中文入口与采纳/放弃按钮清楚可用。
- 从最终实际 DOM 收集的 **21 项语言 ID/中文名称/顺序**另与固定字面预期逐项比较一致；浏览器真正选择的是 **英语和日语**，生成并采纳的是英语 ScriptedModel 候选。没有把其余语言的菜单存在当成模型翻译效果验证，也没有声称日语候选质量通过。
- 另以独立 Python 进程直接读取最终签名文件名所指的真实补丁 PPTX，重算文件 SHA256 并用 `python-pptx` 核对两页文字、表格 42 与图表 `[42,17]`。结果和路径/身份保存在 `independent-built-verification.json`。这仍是引擎补丁产物回读，不是新修订下载验收。
- 本次冻结会话没有额外操作尺寸预设、圆形转场或艺术字；这些固定枚举中文的早前 DOM/隔离源码浏览器证据仍保留在 `NATIVE_WORD_PPTX_SOURCE_ENTRY_GAPS_20261113.md`，不把本次 129JS 一致性扩大为它们在当前生产宿主中再次交互通过。

## XLSX 图标局部修复后的构建身份复核（9bd）

root 仅调整 XLSX 菜单 SVG 尺寸后重新构建，该次 manifest SHA256 为 `9bd8828c7813c0958cb9cde714449fbaa1ceb1c102e6b4a8eba82eaadf84707c`。上一节 `8d4ca139…` 的完整候选烟测证据和冻结副本原样保留；本次另存到 `ai-presets/browser-built-final-9bd8828c-identity`，不覆盖或冒充完整烟测重跑。

- `normalized-identity.json` 将新旧构建中九个唯一配对的改名 JS/CSS 资源文件名替换为对应共享 token，其它字节全部保留。此前实际加载的 **129 个 JS 中 126 个原始字节完全相同，另 3 个仅资源引用文件名变化；归一后 129 个全部逐字节一致**。
- 附带检查全部 **394 个 bundle JS**：归一后唯一代码差异在预期的 `workbook-ribbon`。PPTX 的功能代码没有变化，因此按约定不重复生成/采纳候选等完整专项。
- `entry-summary.json` 记录新冻结副本上的最小真实 HTTP 浏览器验证：PPTX 画布就绪，21 项语言真实 DOM 与上一冻结版完全一致，英语入口打开当前页范围，拼写检查入口打开整稿范围；没有启动模型 job。
- 同次浏览器实际加载 **129 个 JS**，资源集合与旧版映射后的预期集合完全一致，每个响应 SHA256 均与新冻结副本匹配；`errors`、`consoleErrors`、`httpErrors` 均为空。`pptx-entry.png` 已目视检查中文审阅入口和整稿 AI 侧栏。
- 此次只复核入口和资源身份，不新增候选质量、保存/导出、修订或下载验收结论；上节完整生命周期证据通过严格代码身份对照复用。

## XLSX 手势修复后的构建最小续验（6bb）

root 修复 XLSX 原生 pointerup 合成双击遗漏后再次构建，该次 manifest SHA256 为 `6bb0f8ab4f0d66993c135a6174e1e1437dcda38ee61c0c6efa850c82f4b96b09`。本次证据独立保存在 `/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final-6bb0f8ab-identity`；`8d4` 完整链与 `9bd` 最小续验证据及静态副本全部原样保留。

- `normalized-identity.json` 以 `9bd` 冻结副本为基准，只将七个唯一配对的改名 JS 资源文件名替换为对应共享 token，其它字节全部保留。此前实际加载的 **129 个 PPTX JS 中 126 个原始字节完全相同，另 3 个仅资源引用文件名变化；归一后 129 个全部逐字节一致**。结合前次 `8d4 → 9bd` 对照，PPTX 功能代码身份连续可核验。
- 附带检查全部 **394 个 bundle JS**：本次归一后唯一功能代码差异位于预期的 `workbook-main`，PPTX 加载代码没有功能差异，因此没有重跑完整 AI 候选专项。
- `entry-summary.json` 为本次最小真实 HTTP 浏览器续验：PPTX 画布就绪，21 项语言实际 DOM 的 ID、中文名称与顺序均与 `9bd` 一致，英语入口打开当前页范围，拼写检查入口打开整稿范围；模型 job 数量为 0。
- 同次实际加载 **129 个 JS**，集合与 `9bd` 映射后的预期集合完全一致，每个响应的 SHA256 与 `6bb` 冻结副本匹配，`errors`、`consoleErrors`、`httpErrors` 均为空。`pptx-entry.png` 已实际目视检查审阅入口和整稿 AI 侧栏。
- **完整候选生成、明确采纳、撤销重做、放弃、过期候选拒绝、取消与 PPTX 独立回读仍是 `8d4` 的完整链证据；`6bb` 只完成入口和资源身份续验。**本次不新增真实 provider 质量、保存/导出、修订或下载签发验收结论，也没有把 `8d4` 证据改写为 `6bb` 再次完整运行。

## 最终 history 构建最小续验（0015）

XLSX 历史栈修复后的最终构建 manifest SHA256 为 `0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe`。证据独立保存在 `/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final-0015c3b3-identity`，此前三批证据和冻结副本均保留。

- `normalized-identity.json` 以 `6bb` 冻结副本为基准，仅将八个唯一配对的改名 JS 资源文件名替换为对应共享 token，其它字节保留。**129 个 PPTX 实际加载 JS 中 126 个原始字节相同，3 个仅资源引用名变化；归一后 129 个全部逐字节一致**。`8d4 → 9bd → 6bb → 0015` 的功能代码身份对照连续通过。
- 附带检查全部 **394 个 bundle JS**，归一后代码差异仅在 `workbook-main`、`workbook-ribbon`。后续只读 AST 精查记录于 `ribbon-ast-difference.json`：两边解析错误均为 0，在结构可配对的子树中有 266 处局部标识符改名、0 处非标识符叶子差异，另有 1 处真实结构差异——键盘处理条件新增 `event.defaultPrevented || event.isComposing || event.keyCode === 229` 守卫，不能将 ribbon 差异全部称为 minifier 改名。root 确认存在外部并发源码变化；该事件/IME 守卫归入此类变化。**PPTX 实际加载的 129 个依赖不含 `workbook-ribbon`，因此本专项不验收这项额外行为变化。**PPTX 加载代码没有功能差异，故未重复完整 AI 专项。
- `entry-summary.json` 记录本次真实 HTTP 最小入口续验：PPTX 画布就绪，21 项语言实际 DOM 的 ID、中文名称和顺序与 `6bb` 一致；英语打开当前页范围，拼写检查打开整稿范围，未启动任何模型 job。
- 实际加载 **129 个 JS**，资源集合与 `6bb` 映射后的预期完全相同，每个响应 SHA256 均与 `0015` 冻结副本匹配；`errors`、`consoleErrors`、`httpErrors` 均为空。`pptx-entry.png` 已实际目视检查。
- 完整候选生命周期和真实 PPTX 补丁产物独立回读继续引用 `8d4` 完整链证据；`0015` 的结论限于代码身份连续性及入口续验，不表示重新完成完整候选测试、真实 provider 质量测试或保存、导出、修订、下载签发验收。
- 本节证据对应独立保存的冻结构建，不表示整个当前工作区均已验证；root 另发现构建后源码漂移，当前源码变化不由本次 PPTX 冻结资源续验覆盖。

## 冻结构建复用命令

由 root 先完成统一 tsc/build，再在 `frontend` 执行；输出目录须为新目录，脚本将冻结静态目录复制一份，并逐个核对浏览器实际加载 JS 的字节身份。

```bash
PPTX_AI_PRESETS_BUILD=/path/to/frozen/static \
PPTX_AI_PRESETS_DIRECTORY=/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built \
PPTX_AI_PRESETS_PORT=4353 \
node smoke/pptx-ai-presets-smoke.mjs
```

源码层重放可额外设 `PPTX_AI_PRESETS_SOURCE=1` 并使用独立新输出目录；该模式启动临时 Vite，不修改共享 static。

## 保留边界

- 没有真实 provider 消耗或 21 种语言质量评测；ScriptedModel 只证明工具协议、任务上下文与候选生命周期。
- AI 当前只修改已获能力证明的对象；不覆盖母版、复杂只读对象、图像内文字或所有来源的全文翻译。21 项菜单接线不等于 21 项模型效果均通过。
- 拼写指令要求保持页序/主题/数字/样式，实际候选仍按已有通用候选能力验证并由用户明确采纳；没有新增专属“只许改字”后端格式，也不能将该 prompt 写成独立安全隔离保证。
- 完整保存下载链、正式生产权限、复杂工作区已有改动的全回归及四格式完整 AI 工具/流式任务仍不属于本专项关闭范围。
- 未改共享 native-main/app、发布签发或门禁；未完整测试、提交、推送或部署。
