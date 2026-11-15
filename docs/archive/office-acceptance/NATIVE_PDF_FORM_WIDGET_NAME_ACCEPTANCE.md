# PDF 独立字段叶子名称编辑验收（2026-11-11）

## 来源与范围

固定源为 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。`apps/pdf/src/renderer/FormDesignLayer.tsx:568` 的 `FormFieldProps` 明确说明字段名称是 generated, not shown。故本批属于用户持续授权的更多字段属性增量，不能记为固定源现有 UI 的逐字迁移，也不据此宣称固定源缺口计数减少。

复用既有 `editFormWidget`，新增可选 `newFieldName`（完整新名）。仅接受安全 AcroForm 叶子字段、单 Widget、同一父层级改名；名称沿用创建字段的 ASCII 分段规则（总长≤256、≤16段、每段≤64字符、首字符字母或下划线）。根字段可以改根叶子名称。拒绝空名、无变化、非法名称、重复/兄弟/前缀冲突、跨父层级移动、多 Widget，以及与 rect/required 同一项修改。保留既有来源 SHA 和旧完整 fieldName/widgetId/widgetIdentity/expectedWidgetSha256 绑定。来源安全检查继续拒绝 XFA、签名/保护、动作或不闭合字段树等不支持来源。

## 最小实现

`bridge/form-design-properties.ts` 使用 pdf-lib 原生 `acroField.setPartialName`，不重建字段、不重新生成 AP，不移动 Parent/Kids，不改已有值。保存显式 `updateFieldAppearances:false`。写后比对所有间接对象；仅允许目标字段 `/T` 变化，外观流同时比较原始 bytes 和字典，因此包括目标 AP 在内的原有资源、引用与正文都须保持。另回读新名称、旧名称消失、原字段引用、原 Widget 引用和设计身份范围。

写后复核异常通过既有 receipt 返回 `pdf_form_widget_output_review_failed`、实际 bytes/SHA/size 与失败原因，不丢失文件；不得把复核失败标记为通过。公共发布/下载接线由 root 统一验收。

`frontend/src/pdf-form-create.ts` 既有“字段属性”面板新增“新字段名称”，初值为完整旧名；多 Widget 的名称控件不可用。应用按钮只序列化实际改变的属性，单改名称不带出原 rect/required，空操作提示至少修改一项。UI 和草稿结构 validator 均执行同父叶子/独立改名约束，当前模型再复核完整旧身份、单 Widget 和冲突。Undo/Redo、既有预览确认、保存/重开继续复用。

## 定向验证

- 后端新增 `bridge/form-widget-name.test.ts`，先真实 RED 3 项（旧实现拒绝 newFieldName），最小实现后新增3项与受影响旧4项共7/7 PASS。
- 前端新增 `src/pdf-form-widget-name.test.ts`，先真实 RED 3 项（旧属性 validator 拒绝、名称控件不存在），实现后新3项与旧10项共13/13 PASS。旧属性面板测试调整为实际修改必填状态，避免把无修改空操作当作有效操作。
- 覆盖根名称/同父层级名称成功、全间接对象与 AP 保留、旧身份不可复用、无变化/跨父/前缀/重名/非法名称拒绝、多 Widget 拒绝，以及写后复核故障仍保留实际改名 bytes。
- 独立原生序列在 `/tmp/pdf-next-form-name/independent/`：以已有真实浏览器来源及 code 下载为输入，直接原生改名 `party.customer.name` → `party.customer.renamed`，再完整桥接 `setFormValue` 填入 `Alice Updated`。独立 pypdf verifier 已通过字段树闭合、全部原间接对象（仅目标/T例外）、AP内容与引用不变、正文与页面几何不变、新名称继续填值和无关code保持。此证据不冒充本轮浏览器验收。
- 改名 PDF SHA-256 `c6275bd4dc2b76eb34e0abf80a700d7de71c6dd807e9db8b847ef5164c6dbeb3`；后续填值 PDF SHA-256 `5dc66fde024e52ef1cf0e3dd8f7a67b8a0a38ea83c7a5e629c8137d2dcf2a394`。

专属 smoke：`frontend/smoke/pdf-form-widget-name-smoke.mjs`；独立 verifier：`pdf-form-widget-name-verify.py`。沿用真实 grant/cookie/CSRF、冻结静态资产、打包 PDF 引擎、预览确认、保存签发下载和重开；创建 name/code 后拒绝重名、实际安全改名、Undo/Redo、下载重开、新名称填值再下载。变量 `PDF_FORM_WIDGET_NAME_SMOKE_DIRECTORY`、`PDF_FORM_WIDGET_NAME_SMOKE_PORT`（默认4344），以及统一 `PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、Chromium 路径。脚本 Node syntax/Python compile 已通过；统一冻结后的真实 browser 已通过，证据 `/tmp/pdf-vector-rename-convert-form-browser/summary.json`，37 个实际 JS SHA 与同一 static 匹配，来源保持，各类 errors 为空；4 次保存完成创建 name/code、拒绝重名、实际叶子改名、Undo/Redo、预览确认、下载重开和新名称后续填写。独立 pypdf 复读改名仅改 /T、值/树/引用/AP/正文保持，最终界面已目视。改名实际 PDF SHA-256 `007c4d200fff36679eded381971a261d62ed68b627adea0fa2ee36c8efab674d`，后续填值实际 PDF SHA-256 `d347b8121ba7fb814f05e4f48e49223181a7ada7402deea66322e24cfc51c8af`。恢复草稿漏传 newFieldName 的 host 接线以真实 RED→GREEN 修复；HTTP renameFormWidget 后置故障同新运行包通过并保留下载，日志 `/tmp/pdf-vector-rename-convert-http.log`。统一身份见 `NATIVE_PDF_VECTOR_RENAME_CONVERSION_ACCEPTANCE.md`。

## 保持未完成的边界

不含跨父移动、父节点重命名、字段合并/拆分、共享多 Widget 改名、引用字段名的任意脚本重写、XFA 或数字签名字段编辑。复杂字段来源不会因改名入口而扩大支持。不新增 OCR，不改变字体、值、区域或 AP。
