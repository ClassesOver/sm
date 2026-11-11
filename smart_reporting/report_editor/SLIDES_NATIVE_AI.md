# PPTX 原生 AI 宿主与能力范围

固定 GenOffice 来源：f8c17004fb730df11f0f743164ffd8b4281bb38c。
来源 apps/slides/src/renderer/App.tsx 的 askTargets、askScopeQuote 和 pushAiPreset 使用持久对象身份、页面与选区文字引用后提交 AI。
本地宿主遵循这些真实语义，复用当前画布/检查器选区及同一份 NativeDraft；没有把 legacy 面板解除 hidden/inert 作为完成条件。

## 已接通

- 中文“AI 助手”入口；选择当前对象、当前页可编辑对象或明确授权整份演示文稿。
- 请求只提交来源 SHA、完整人工草稿、对象身份和用户指令。服务器从可信原文件重建对象，叠加人工未保存文字与几何；选区之外文字不进入所选范围的 prompt。
- create_native_slides_ai_service 使用既有 SlidesAIProposal、AgnoSlidesProposalPlanner、Reporting 结构化输出执行器和真实 Agno generator agent，未新增模型协议或正文伪工具解析。
- 复用 NativeAIService 的任务轮询、上下文授权、完整草稿摘要、取消、显式采纳和关闭。PPTX 专属 /api/slides-ai/* 路由沿用原生会话与同源 CSRF。
- 每次提交先生成 clientRequestId；预览准备也放入已登记的后台任务。cancel-request 根据上下文与请求身份取消，提前取消创建一小时墓碑，丢失 start 回执也不会依赖未知的 editId。卸载请求用 keepalive；旧取消失败不能覆盖新任务状态。同请求重试返回同任务，禁止用相同请求身份混入另一份指令或草稿。
- 候选先经过真实 PPTX 引擎预览，再显示中文文字差异、几何、页序与主题；此处的候选预览是结构化差异，不是另一份画布截图。
- 点击“采纳到草稿”前后均校验完整本地草稿，服务器再次验证上下文、来源 SHA、完整草稿摘要并重跑真实引擎。返回的单个 editSlides 合并保留人工背景、格式、几何等操作。
- 采纳写入既有 NativeDraft，共用撤销/重做、刷新恢复、真实画布预览与保存修订。采纳不直接发布或覆盖原文件；业务事实保持人工复核软提示。
- 当前对象/当前页范围支持已有可编辑对象的文字与位置大小；整稿范围还支持全页排列和既有三种商务主题。

## 仍有明确缺口

- 原生 AI 配图、改图、图表/表格生成与编辑没有接通；legacy .slides-image-tools、图表 AI 仍禁用，未新增 Plotly 或交互图。
- AI 不支持新增/删除页面和对象、母版/版式重建、动画/转场、SmartArt、源图片编辑、视觉理解或全新演示文稿生成。已有手工这些能力不等同于 AI 能力。
- 有新建/删除页面的未保存草稿须先保存，再为来源对象生成候选；所选范围最多 100 对象，结构化候选最多 50 edits、上下文 48,000 字符。
- 没有声称完整移植固定源桌面 AI 队列、截图附件、模型选择或通用工具系统。

## 验证边界

- test_slides_native_ai.py：未保存选区、越权目标/页序/主题拒绝、完整草稿过期、真实 PPTX 引擎预览和 python-pptx 独立回读、CSRF/版本/跨公司/严格输入、取消与引擎拒绝。
- slides-native-ai.test.ts 与 slides-native.test.ts 的 AI 贯通用例：中文选区引用、候选不自动修改、采纳期间二次快照检查、单一草稿撤销重做及保存。
- 浏览器命令：NATIVE_GUI_PREVIEW=1 PPTX_SMOKE_MODE=native-ai PPTX_SMOKE_PORT=4199 PPTX_SMOKE_EVIDENCE_DIR=/tmp/pptx-native-ai-evidence node smoke/pptx-native-save-smoke.mjs。要求 root 已统一构建；该模式明确使用确定性 planner 路由夹具，预览/保存为真实引擎并独立回读下载文件，不冒充真实模型 endpoint 探针。


## 取消契约修复轮浏览器证据（2026-11-11，成功但非最后构建）

- 该轮 manifest SHA256：2c6784d0ba3af88b1206e519d1a3859b2d34f56fa4f1c2a21b0af7cefa6f3b8b；由 root 执行最终 build、预算与预算契约，均 exit 0。本专项未自行 build。
- Chromium 140.0.7339.16，built preview 端口 4199，native-ai 模式成功；与旧构建证据目录分开保存于 /tmp/pptx-native-ai-final-20261111-cancel-request。
- 实际浏览器脚本：lazy-slides-native-ai-DcZfcDj8.js，6129 bytes，SHA256 f0e2b2b15f9e5461e7ebd1616e67167d3cbc09398608fa1c0dd15f46f58f6431；lazy-slides-main-CPNvLhqD.js，158443 bytes，SHA256 6f0ad150897663bc23d2c6fa78d4dc1e829dadae5ffbb298ccb16b57e7f23d59；lazy-native-office-view-Xom72R8f.js，14817 bytes，SHA256 a003efaecfb4147d2ae343aa63491074c294a7dc64b3d7d94946bcc5883dc3f5。
- 浏览器检查“开始”“设计”中文标签，以及 96 个命令按钮各有一个 aria-hidden SVG 图标，无不合格项；AI 助手可见，引用人工未保存文字，候选不自动修改。草稿变化时拒绝请求采纳，显式采纳一次，Undo/Redo 后保存为修订 2；请求级取消实际发出一次。
- 真实 PPTX 预览/保存后，下载文件由 python-pptx 独立回读为“AI候选标题”，尺寸保留 9144000 × 6858000；原文件 SHA256 4fa97b4c327c7cc1af20ba8c261d0a60c882d7f5802f828c599d37e6b72bd79d，下载文件 SHA256 54c212244a72d3b9e7ba1e21d3324d5958b2e7421c7e22a891564106f40c942a。
- 目录含 source.pptx、downloaded.pptx、after-edit.png、evidence.json；JSON 记录实际全部 JavaScript 响应身份。planner 明确是 deterministic-route-fixture；此证据覆盖浏览器及真实引擎，不声称调用了真实模型 endpoint。
- 取消专项：后台 10 项定向用例通过；提前取消墓碑、预览中取消且 start 回执丢失、相同请求重放与不同 payload 拒绝均有测试。前端审查两项 P2 回归、7 项 AI 宿主用例与原生草稿贯通测试分别通过；TypeScript 完整检查 exit 0。兼容回归中的既有 501 次 DOM 事件单例需 60 秒命令时限，独立验证通过 41.2 秒；未更改其生产逻辑或永久测试阈值。


## 最后 verified 构建浏览器证据（2026-11-11）

- 本轮最后 manifest SHA256：8f866be146d8f6475808caae7e7175d5ea14767c84867476b3c86f5e80cc6504。前节 2c6784 构建验收成功，但不是最后 manifest；最后共享入口更改后，本专项仅对新资产重跑 native-ai 单项，未改代码、构建或断言。
- 新证据目录：/tmp/pptx-native-ai-verified-20261111，含 source.pptx、downloaded.pptx、after-edit.png 和 evidence.json；没有覆盖此前任一目录。
- 本轮实际加载 JavaScript 中，105 项与 2c6784 证据逐字节摘要相同；仅 native-api、native-main、unified-main 三项共享入口因新引用改变。slides-native-ai、slides-main、native-office-view 的路径、字节数及 SHA256 与前节完全一致。
- Chromium native-ai 单项 exit 0：开始/设计中文标签、96 个命令按钮各含一个 aria-hidden SVG；人工未保存文字引用、候选不自动写、过期草稿拒绝采纳、显式采纳一次、请求级取消一次、Undo/Redo、保存修订 2 及真实下载 python-pptx 独立回读全部通过，尺寸 9144000 × 6858000。
- 本轮源文件 SHA256：84b18e5e284cc2a8be5c4da58c787fd2b856a826ccc7313b502ec6546edfca78；下载文件 SHA256：f7d4ef8b869a87ef186bd08b9941715292f2db80d1671fa8dc723155e971b2ff。源文件未被保存操作修改；下载对象身份与回执一致。
- planner 仍明确是 deterministic-route-fixture，预览与保存使用真实 PPTX 引擎；本条不声称调用真实模型 endpoint。最终会话 98333 exit 0，已无在途专项会话。

### 根线程最终目视与本地化边界

根线程已独立核对最后 8f866be 构建的 evidence.json（ok=true、修订2、显式采纳1次、取消请求1次）并目视 after-edit.png。功能区静态命令/AI宿主中文和图标正常；来源元数据中的布局名 Blank、对象名 TextBox 1 等仍按来源原名显示。自定义文档对象名应保留；内建标准布局的显示名中文映射仍需专项补齐，不能把静态按钮验收扩大为全部 UI 文本完全中文。完整四格式对齐仍未完成。
