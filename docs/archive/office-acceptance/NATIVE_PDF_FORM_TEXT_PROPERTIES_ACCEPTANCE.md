# PDF 已有文本字段属性编辑验收（2026-11-11）

固定源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批支持已有安全独立文本 Widget 的多行、最大长度、文字对齐与字号修改。只对可证明为 ASCII 当前值、单 Widget、未签名/保护/动作字段及标准字体的字段开放；CJK、自定义字体、密码、富文本、日期及多 Widget 保持拒绝。最大长度不得小于当前值，设为 0 表示移除限制。每个操作独立保存，写后复核异常只告警并保留已验证身份的实际产物。

实现位于 `reporting/pdf_engine/bridge/form-text-properties.ts` 与 `report_editor/frontend/src/pdf-form-text-properties.ts`，经现有 bridge operations、PDF operation validator、PDF 主界面、preview/review 确认及回执类型接入。`LOCAL-SHA256.json` 包含本批引擎源和专项测试校验值；vendor 原始 `sourceSha256` 未更改。

专项验证：前端属性测试 4/4、引擎属性测试及集成测试 6/6、表单渲染宿主专项新用例 2/2、preview confirmation 1/1、Vite chunk 名称检查、针对新增 operation 的 HTTP 后写故障非阻断用例与签发静态守卫 2/2。前端范围 typecheck 和 production Vite build 通过。没有运行完整测试套件。

真实浏览器使用冻结 production assets、PDF.js、grant/cookie/CSRF、packed runtime、原生 preview/save、签发下载及重开，测试记录 `/tmp/pdf-continue-form-rerun/summary.json`；独立 pypdf 回读 `/tmp/pdf-continue-form-rerun/independent.json`。浏览器无页面/控制台/HTTP/asset 错误，来源身份保持。属性修订下载 SHA-256 `0e5b6c237f82ddf6b7498784e2d95d848fc4dcf8c93fd31472b3978c09df6744`；清除长度限制后的修订 SHA-256 `1edb0f2a58caef2a7d863bdb310cfe4eb1e2edb5a49439cf07bfd8fef66c54bd`；最终字段值修订 SHA-256 `a8290bb9520654f1a9a6128df8fda80a4a3cba04fc0140bf6b3c51a9114b8a0f`。独立回读确认属性 AP 更新、字段引用保留、当前值保留，以及之后的 `Alice Updated` 表单值实际写入和重开。

这不覆盖任意 PDF 字体/表单结构；XFA、签名、保护来源、富文本与复杂多 Widget 属性继续保留为缺口。验收仅证明此固定 fixture 和白名单边界。
