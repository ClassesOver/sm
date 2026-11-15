# PDF 安全单选按钮逻辑删除验收（2026-11-11）

## 来源与安全范围

固定源 `/home/junge/pros/genoffice-source-full` commit `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/pdf/src/main/save-pdf.ts:1044-1050` 已有多 Widget 删除分支，使用 `removeWidget` 与 `detachAnnot`，未同步移除单选导出选项。本批复用既有 `removeFormWidget`，保持来源 SHA 及 fieldName/widgetId/widgetIdentity/expectedWidgetSha256 绑定；不新增操作或重造字段树。

限定上一批已闭合的安全互斥单选组（2–64个Widget），只删除未选中且非默认值的一个按钮，至少留下一个。组中所有选项/状态/AP/树/引用/actions 均通过既有严格复核；额外要求原始 Opt 缺失或严格字符串数组且长度与按钮一致，Kids/Opt/目标页Annots若为间接数组必须引用唯一，每个按钮 `/P` 与实际唯一页面归属相符，间接 `/V` 与 `/DV` 先解析再判定。共享AP、当前/默认按钮、任意其他多Widget、坏选项/引用、XFA/签名/动作继续拒绝。

这是活动字段树逻辑删除，不承诺擦除 PDF 历史字节或脱离的原外观数据。

## 最小实现

`bridge/form-design.ts` 对每个按钮给出专属 `radioRemovalEditable` / `radioRemovalReason`，不扩大旧 `removable`，避免误扩 `editFormFieldRequired` 权限。原生 `acroField.removeWidget(index)` 与 `removeExportValue(index)` 同步减少 Kids/Opt；只从已核验 Annots 的原生 PDFArray 删除相应引用，并 `context.delete` 已脱离且无外来引用的目标 Widget 对象。保留字段 ref、幸存 Widget ref、原 on-state 名称、当前/默认值、其他按钮与所有原AP流/资源/正文。

本轮真实定位 `page.node.removeAnnot` 会归一化未 normalize 的页面，额外包装 Contents 并修改 Resources，故新单选路径直接调用已核验原始 Annots 数组的 `remove`，避免正文副作用；不是手工重建树。旧独立字段删除保留既有原生语义。快照对所有 PDFStream 使用原生 updateDict/getContents，以 encoded bytes+dict 对比，避免旧路径内存 PDFContentStream 与保存后 PDFRawStream 类型不同而产生误警告。

新增 `removeDesignWidgetWithReceipt` 返回 bytes/sourceSha256/sha256/size/appliedOperationIndices/skippedOperations/previewDigest。写后加载、字段树、完整间接对象/原始流、活动Widget消失和单选幸存值/选项/ref复核失败，返回 `pdf_form_widget_removal_output_review_failed` 与具体原因及实际文件，不丢产物、不把验收标通过。旧 `removeDesignWidget` bytes API 委托新入口取 bytes 保持兼容；公开 operations/CLI receipt 接线由 root 完成。

2→1 后专属删除资格 false。单 Widget radio 原本不在旧独立字段删除支持列表（仅text/check/dropdown），故不新增整组删除权限；原有text/check/dropdown单字段删除语义保持。

前端 `pdf-form-design.ts` 的模型/stage/列表接受旧 removable 或新完整安全组专属资格，重新核对组完整性、唯一ID、选项与选中值一致及所有兄弟设计资格。按钮文案为“删除单选按钮”，当前/默认值不可用；保留Undo/Redo、单独预览保存及逻辑删除提示。未改必填属性UI。

## 定向证据

- 新 native `bridge/form-radio-removal.test.ts` 初次真实 RED4项（资格/receipt缺失）；实现后发现原生直接构造层级fixture会产生重复孤儿父节点，被已有safeAncestors正确拒绝，改复用实际createDesignField安全构造；随后跨页失败真实定位PageLeaf归一化副作用并修复。
- 新native初始4项及新增间接V/DV与外来P硬化1项：5 PASS，日志 `/tmp/pdf-next-radio-removal/native-green-hardened.log`；新增硬化先真实 RED，日志 `indirect-red.log`。涵盖2→1、3→2、跨页、中间选项不重编号on名、当前/默认值拒绝、共享AP/数组、坏Opt、动作、旧身份拒绝、写后故障保实际bytes。
- 旧 `form-design.test.ts` 4项通过，保留多Widget非radio及保护来源拒绝，见 `native-green.log` 中旧4PASS（该轮新测试仍有fixture问题，不将整轮标为通过）。
- 新UI2项 + 旧 `pdf-form-design.test.ts` 4项共6 PASS，日志 `ui-green.log`，此前新2真实RED `ui-red.log`。
- root新增公开radio操作2项及旧公开独立字段2项共4 PASS，日志 `public-green-stream-canonical.log`，验证专属capability、正常receipt及后置具体故障原因保留；未重复完整测试。
- 窄TypeScript仍只有6项既有宿主声明错误（resourcesPath两项和@genoffice依赖四项），无本轮新增错误；`typecheck.log` 不记为完整类型检查通过。
- 独立序列 `/tmp/pdf-next-radio-removal/independent/` 使用实际来源，创建Yes/No/Maybe及code，通过完整公共桥接删除中间No，再填Maybe。独立pypdf复读确认仅精确Kids/Opt/Annots引用与目标Widget对象消失，所有其他原间接对象和原始AP流不变；Yes保持，幸存on名/0与/2不变，后续Maybe填写成功，字段/code/正文/几何不变。`native.log`、`independent.json` 已通过。这不冒充本批真实浏览器结果。
- 删除PDF SHA256 `584623c4c3bd7fc59a68b5436b784d9f94a2ac770ace3e350cb18d3504ed7b6c`；后续Maybe填写PDF `f8c514fd7cac47fd3d9193d94b0a3a2b2d510f17cbb703dddcc830d5e4f82a96`。

专用浏览器脚本 `frontend/smoke/pdf-form-radio-removal-smoke.mjs` 默认端口4347，变量 `PDF_FORM_RADIO_REMOVAL_SMOKE_DIRECTORY` / `PDF_FORM_RADIO_REMOVAL_SMOKE_PORT`，复用 `PDF_SMOKE_STATIC_DIRECTORY` / `AGENT_REPORTING_PDF_ENGINE_DIR` / Chromium路径。流程4次保存：创建3按钮、创建code、删除No、填写Maybe；真实grant/cookie/CSRF、冻结资源、打包引擎、Undo/Redo、预览确认、签发下载重开及独立verifier。Node语法与Python编译已通过；统一真实browser/HTTP故障验收待root追加，尚未提前记通过。

## 本批统一最终验收

统一冻结static/runtime的真实browser已exit0：`/tmp/pdf-measure-radio-currency-form-browser`，37个实际JS身份匹配且四类errors为空、来源未变。创建三按钮与code、删除No、填Maybe四次保存、Undo/Redo、实际预览确认、签发下载重开及独立pypdf均通过；最终UI已由root目视。删除9011 bytes/SHA `053dec2e0980aa5e8837cf07ea5ab2f75bee1ff82dfdb8cec920e3dfc48ccccc`；后填9130 bytes/SHA `168903d5bab8ec5984cc43db9383143d9cc1bd49655f58f965c62a46abf1639c`。完整对象不变断言仅适用于删除步骤，后填按原语义改变V/AS。公共operations/CLI已接WithReceipt，HTTP新增removeRadioWidget后置故障下载通过，签发静态守卫通过。统一身份/预算/其他专项见 `NATIVE_PDF_MEASURE_RADIO_CURRENCY_ACCEPTANCE.md` 与 `/tmp/pdf-measure-radio-currency-final-evidence-20261111.json`；整体多Widget能力仍未完成。
