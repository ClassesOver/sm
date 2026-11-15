# PDF AcroForm AI 填写验收记录

2026-11-11。四格式完整 GenOffice 对齐仍开放，本文仅记录已有 PDF 交互表单填值与助手前端增量。

## 能力与身份

固定源 `apps/pdf/src/renderer/ai/tools.ts` 的 `list_form_fields` / `apply_ops` 在本地通过真实 Agno 注册。用户明确选择 fieldId；工具仅读取冻结授权字段的实际当前值及选项，分页读取全部内容后才能登记填值。支持 text/checkbox/radio/choice；模型仅提交 setFormValue 的 fieldId 和 value/checked，原件 name/kind/hash 由服务器恢复，服务再次校验。只读/不支持字段、签名来源、伪造身份、越权、重复、错误类型及错误选项均拒绝。不能把正文中的 JSON 当操作执行。

任务复用现有状态、SSE、取消生命周期。原件身份与完整人工草稿绑定；草稿先真实预览、同字段填值覆盖合并，未选字段及其他安全操作保留。字段结构与无法可靠投影的草稿要求先保存。候选经真实 PDF 引擎预览，明确返回 applied/skipped，采纳重新验证来源、完整草稿和预览摘要。只采纳到草稿，不自动保存。表单 AI 需要 AI 与 PDF 编辑能力，不依赖 PDF 原位改字开关。没有变更报告发布链。

## 定向验证

工具 14 项边界/真实 PDF/Agno 测试分批通过；另新增实际 Agno 工具 schema 参数说明契约 1 项通过。服务/API 9 项分批通过，覆盖真实填值及人工草稿覆盖、伪造身份、权限/CSRF/版本、提前取消、吞取消、采纳预览期间取消、超时和独立文字开关。前端初始 5 项通过，覆盖默认不选、明确授权、差异/采纳、迟到取消、草稿冲突、实际 API 契约。后续侧栏与输入变化测试另记。不重复运行完整测试。

## 真实模型

`deepseek-v4.1-flash` / 现有 production_model 工厂，实际 NativeEditorService、workspace/grant 会话、Agno 工具与 PDF 引擎。只使用 `/tmp` 合成文档，不修改生产文档。

首次两链读取完成但未产生可采纳操作，按未通过保留 `/tmp/pdf-ai-forms-real-provider-20261111-first-failed.json`。实际工具 schema 的 operations 元素为任意 object，缺少参数布局说明；补精确 JSON 示例与 Args、成功回执后停止指令后，两链复验通过，总13.12秒（文本6.78秒；checkbox/choice/radio5.66秒）。期间一次探针重用workspace路径冲突属于夹具失败，保留独立记录，随后使用新目录。

最终证据 `/tmp/pdf-ai-forms-real-provider-20261111.json` 与对应 `.py`。root 独立重新计算来源和候选 SHA，用 pypdf 回读确认：文本 Original→Lin；另一链 consent /Off→/Yes、region north→south、plan /basic→/pro。各链未选字段与秘密字段保留，秘密值未进入授权读取；原件 SHA 不变，实际全部操作应用，无跳过。

## 前端验收状态

正在按固定源右侧 AI dock 和当前功能区入口统一 PDF 阅读、审阅、填表面板。最终冻结构建、浏览器、类型和体积结果待完成后填写；不得把以上服务探针等同前端已验收。

## 最终 PDF 助手前端与浏览器

阅读、批注审阅和表单填写通过 `pdf-ai-dock.ts` 停靠到同一360px右侧栏，保留现有功能区入口；<=900px用抽屉。统一中文header/SVG/输入/工具进度和差异，切换或关闭通过原控制器取消任务。填写要求纳入冻结快照，输入变化清除旧候选，防止当前要求变成Mei却仍采纳Lin；新增pending start/accept两项窄回归通过。dock切换/关闭保留画布、启动浏览器document及动态加载两项窄回归通过。原5项不重复。四格式前端差距另见 `NATIVE_AI_ASSISTANT_FRONTEND_ALIGNMENT.md`，不称已完成四格式助手。

最终Vite构建44.70秒成功，冻结目录 `/tmp/pdf-ai-forms-20261111-final-build/static`。表单与dock独立按需加载；PDF main251040字节（245.2KiB）低于250KiB cap，未提高阈值。早期启动按钮误用局部PDFDocumentProxy的document问题已修为window.document，并有实际启动回归。

最终built浏览器 `/tmp/pdf-ai-forms-20261111-verified/summary.json` 三链通过：明确选四字段→真实Agno工具→中文差异/SSE→采纳到草稿；吞取消任务不能复活；阅读/填表dock切换与关闭、780px窄屏抽屉。桌面助手位于画布右侧，画布宽度>500px；窄屏dock360px。采纳前草稿不变，采纳后实际字段Lin、/Yes、south、/pro，秘密字段原样；无save/export POST，原件SHA不变。

root独立核验manifest `23832cb6163ab7d191f3b49e6126d13b5372588661dc5ce20131bd4412f40c98`、33实际JS资源、来源与候选PDF摘要，并用pypdf复读字段；目视候选截图。页面/console/HTTP错误均[]。浏览器模型为ScriptedModel经真实Agno，与前述真实provider2链分别记录，不混称。

全局tsc仍失败：pdf-text-selection.test的styleRuns、slides-clipboard-link-main.test的unknown、workbook-main的FRange字段；本轮表单/dock无报告错误。冻结构建budget还有四项失败：docx-main254.5>250KiB、docx-render765.2>710KiB、workbook-engine443.3>428KiB、workbook-main270.0>253KiB。以上保留失败，不扩大cap、不宣称全前端检查通过。最终scoped Ruff、JS语法及相关tracked diff whitespace检查通过。
