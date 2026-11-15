# PDF 混合文字标注、表单字型及 PPTX 位置验收（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批未包含 OCR、未提交部署、未启用生产功能开关；整体 PDF 对齐仍未完成。

## 统一冻结身份

- 静态目录 `/tmp/pdf-next-three-domains-static`，manifest SHA-256 `943caf9056736c1d02e70008ee7178796e889a387a1c0b16156403a8a550ce06`。
- 最终运行包 `/tmp/pdf-next-three-domains-runtime-final`，`dist/cli.mjs` SHA-256 `e1f9caddc49a241815a3a0f6da7dfe2230cf7b338847fc93f0e3586cff0abb12`。
- 三条真实浏览器链路均使用该静态/运行包，分别实际核验 37 个 JS 响应的 SHA 与冻结文件一致；来源保持、页面/控制台/HTTP/资源错误均为空。
- 构建与打包日志 `/tmp/pdf-next-three-domains-{vite,bundle-final,package-final}.log`；PDF 主入口 244289 bytes、表单 controls 29185 bytes，维持原预算，未提高限制。
- 总证据 `/tmp/pdf-mixed-fonts-position-final-evidence-20261111.json`。`LOCAL-SHA256.json` 为 160 项本地快照；converter 48 项 local SHA 匹配，原始上游身份未覆盖。

## 三域实际结果

1. 样式改字与新增文字标注同批：`/tmp/pdf-next-mixed-browser-root01/{summary,independent}.json`。实际下载 `5af44a552aa70448ad05058d7709fc00a96da4ced9b5e3df29314e9ba9753aa9`，分段字体/字号/基线、Underline/Squiggly 原坐标与 AP、其他页正文均由 pypdf 独立核验；Undo/Redo、实际预览确认和重开通过。限制与测试见 `NATIVE_PDF_TEXT_MARKUP_MIXED_ACCEPTANCE.md`。
2. 安全已有文本字段 12 标准字型选择：`/tmp/pdf-next-form-fonts-browser-root01/{summary,independent}.json`。实际经历 Helvetica → Times-BoldItalic → Courier-BoldOblique → 再填写；最终下载 `b5166aaf163d2cc4f059e62860e1b50b8e61287f9346f5cc1c7ab64f3b5424c9`。独立读 AP/DA 确认 Courier-BoldOblique18、黑色、Alice Updated；引用、无关字段 AP、正文保持。修复了后续填值重置 Helvetica 的确定回归，保留超宽裁切的已知边界，见 `NATIVE_PDF_FORM_TEXT_FONTS_ACCEPTANCE.md`。
3. PPTX 文本框位置：实际签发下载 `def96d700564eef6e51e9f6169143ce92e1afc21d096a50ebc2786b6e501dc4c`，浏览器证据 `/tmp/pdf-next-pptx-position-browser-root01/{summary,independent}.json`。实际下载经 host LibreOffice 渲染及 position verifier `/tmp/pdf-next-position-lo-verification.json`，7 个文字框明确 noAutofit，左右列 X 残差 0.967/0.991pt，原约4.8pt漂移明显减少；16pt行距、表格、图片和 Mono caption 保持。首行 baseline 仍差6.35pt，`overallFidelityPassed=false`，保留具体告警并照常提供已核验身份的实际下载。见 `NATIVE_PDF_PPTX_TEXT_POSITION_ACCEPTANCE.md`。

三域最终画面与 host 渲染已目视检查。fixture 仓储为内存实现，测试证明原生 HTTP、grant/cookie/CSRF、PDF.js、packed engine、publication、下载/重开闭环，未冒称真实生产持久化或权限/网络部署验收。

## 回归、审阅与未通过的检查

- 各专项保留实际 RED/GREEN：文字 native 8 项、UI 新2+旧样式2；表单字体新13+旧边界5、填值回归2、UI新2+旧属性4；PPTX 新2。没有重复完整测试。
- 交叉只读审阅发现跨页 UserUnit 预检遗漏，真实探针复现后已补回归和全部受影响页写前检查；已有安全来源标注的 subtype/quads/AP 保持也有新增专项。未借此开放表单/保护/任意混合。
- 最终运行包的新增混合复核故障、第二阶段 writer 失败回执、字体属性复核故障与签发静态守卫共4项通过，日志 `/tmp/pdf-next-three-domains-http-final-green.log`；验收失败仍返回实际下载和 validation 告警。
- 前端完整 `tsc --noEmit` 未通过，报告的是并行 Word 测试 `docx-ruler.test.tsx` 的 `extendedIndents` 类型错误；引擎 scoped strict 检查仍有既有 dispatch 依赖类型错误，不能称全项目类型检查通过。新纯读器 strict 检查通过，新增 mixed 测试自身类型错误已修正；本批不修改无关 Word/旧 dispatch。

下一步仍包括页面内完整游标/自动重排、更多安全混合组合、复杂字体与首行基线保真、任意复杂多 Widget/XFA/签名。窄表单长文本自动适配尚未实现。
