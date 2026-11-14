# GenOffice PDF renderer sources

Upstream: https://github.com/genspark-ai/genoffice at `f8c17004fb730df11f0f743164ffd8b4281bb38c` (Apache-2.0; `LICENSE`/`NOTICE` alongside).

| Local file | Upstream path | Status | SHA-256 |
| --- | --- | --- | --- |
| `renderer/stamps.ts` | `apps/pdf/src/renderer/stamps.ts` | byte-identical | `e8b57e2ac9ae8bc022753ce992da44b2ba7e62bc924901fc44df761a98509e88` |
| `renderer/measure.ts` | `apps/pdf/src/renderer/measure.ts` | byte-identical | `4d2ccdb5cc2bb69703a6e0e7fe708a49e1101d001ab75c220913c0dd0670e6dd` |
| `renderer/image-bake.ts` | `apps/pdf/src/renderer/image-bake.ts` | byte-identical | `bf1b8eaab654e42e80092ed66044e21dd95efb77376798de9e23459151743f50` |
| `renderer/cutout.ts` | `apps/pdf/src/renderer/cutout.ts` | byte-identical (only `PixelImage` is used) | `907bf9b770b660cdfca6d80ae91e2aed8f89a11831f4eeb023b2f73486b9a26e` |
| `renderer/heading-outline.ts` | `apps/pdf/src/renderer/heading-outline.ts` | byte-identical | `5747e7f2cde617af331f62e33c57ad3079a27d94e5e413354f822ba5aa2ed24a` |
| `renderer/OutlinePanel.ts` | `apps/pdf/src/renderer/OutlinePanel.tsx` | type-only `OutlineNode` excerpt | `82f8870ac279eeeb89aa6c0d9655752f237bd03e69f9da143faf653bc94c2c45` |
| `shared/ipc.ts` | `apps/pdf/src/shared/ipc.ts` | adapted: `StampInput`, `OutlineEntryInput`, and detector form types | `603b404e629c6fd4c6298ec06c07ae5f1e69e32ef86120834405e4f22d6fcf29` |

`heading-outline.ts` is the pinned font-size-tier fallback used only when embedded bookmarks are absent or unreadable. The native host follows the upstream App loading lifecycle: asynchronous scan, document-identity cancellation, and embedded-bookmark priority. Its generated tree is read-only navigation and is never assigned to the editable bookmark model or saved to the file. Only the type dependencies are excerpted; the heading implementation is byte-identical.

`stamps.ts` rasterises the watermark and header/footer bars with a browser canvas and builds
`StampInput`s (`buildStamps`, `DEFAULT_WATERMARK`, `DEFAULT_HEADER_FOOTER`). The native editor
uses it unchanged for Edit ▸ 水印 (pinned `StampDialog` → `setStamps`), then offsets each rect by
the page CropBox origin and sends the PNGs to the PDF bridge, which hands them to the pinned
engine's `stamps` stage.

`measure.ts` provides the calibrated measure tool's `parseCalibration` / `formatLength`; the native editor keeps
the scale for the session only (as upstream) and writes the formatted label into the engine's `measure` drawing.


## Selection style helpers (2026-11-11)

Local ../../pdf-selection-style-source.ts copies apps/pdf/src/renderer/color-runs.ts at the same pinned ref. The helper body is byte-identical; only an initial provenance comment is added.
Upstream SHA256: 38139b354fb401b27c00487423eb4b7548f66a1692cbda35f0f1d28d16808bc9.
Local SHA256: 7ed330f5f5cf5ec0f7c5dcb3419cf5b0cd00728a3fa08a3cf4582da5f69d4382.
Existing Apache-2.0 LICENSE/NOTICE apply. These are UTF-16 style patch/splice helpers, not a new layout engine.

2026-11-11: local host adapters preserve the fixed App.tsx Ctrl/Cmd+Enter replacement submission through the existing guarded button, and add fixed FormDesignLayer/App single-widget canvas selection and 1/10pt keyboard nudge using the existing identity-bound rect operation. Safe sources remain default UserUnit only; shared fields, drag/resize and arbitrary mixed drafts are not enabled. Local UI helpers and styling are not upstream source files, and fixed upstream hashes remain unchanged.

`image-bake.ts` supplies `cropRect` for the existing-image crop footprint so the draft rect equals what the
PDF bridge recomputes from the same pinned function (the bridge vendors the same file under `reporting/pdf_engine/src/renderer/`).

## Read-only document comparison (2026-11-13)

Pinned commit remains `f8c17004fb730df11f0f743164ffd8b4281bb38c`.

| Local file | Upstream file | Adaptation | Upstream SHA256 |
|---|---|---|---|
| `renderer/ComparePanel.tsx` | `apps/pdf/src/renderer/ComparePanel.tsx` | byte-identical | `eab70103cacee75246de44278eeee6c04f923d2d2bee3de85421e1ced593e43f` |
| `renderer/compare-text.ts` | `apps/pdf/src/renderer/compare-text.ts` | byte-identical | `9db103542dafee874d78fcd6d26d4e7a8f45f55568e25e77099b0cad7868ccdf` |
| `renderer/i18n/locale.ts` | `apps/pdf/src/renderer/i18n/locale.tsx` | type-only browser boundary for `TFunc` | source runtime not copied |

`pdf-compare.tsx` adapts fixed App.tsx `runCompare` / `compareSides` (lines 4435–4471), retaining saved-source semantics and the original normalized, page-aligned LCS with its 4000-line truncation. Desktop `compareReadPdf`/`compareReadOpen` IPC is replaced with a user-triggered browser file input and the same PDF.js text extraction on both sides; the second file stays local. Its name, actual byte size and SHA256 are recorded for the active comparison. No text from editor drafts is substituted. Unlike upstream unapplied redaction marks, local redaction operations are persisted edits, so all local unsaved operations require saving first.

Closing/canceling the panel or disposing the host invalidates asynchronous results and destroys the picked file's PDF.js loading task. Original source pages remain the navigation authority; extra pages in the selected document are listed but cannot navigate to nonexistent source pages. Image-only or empty text pages carry an explicit text-only/no-OCR limitation, not visual-equivalence claims. No comparison action writes draft operations, source bytes, server file registration or publication state. Existing Apache-2.0 LICENSE/NOTICE apply.

## 确定性表单字段检测（2026-11-13）

`renderer/form-detect.ts` 原字节复用固定源 `apps/pdf/src/renderer/form-detect.ts`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`，SHA256 `79ea4b270abe27051af123c8cede8700e6961ad1e4957c021d622dbe8e015805`。`shared/ipc.ts` 仅追加同源 `FormFieldKind` / `FormFieldInput` 类型片段，未引入桌面 IPC 或运行时。现有 Apache-2.0 LICENSE/NOTICE 适用。

`pdf-form-detect.ts` 为本地来源身份适配：PDF.js 读取来源文本与图形、固定源检测、既有控件占位排除与唯一命名。候选绑定来源摘要/页身份/原页面坐标；页面、来源、草稿或权限变化丢弃旧结果。原有对象 dialog 展示候选且必须逐项确认；只有确认时调用已有 `stagePdfFormCreation`，不改变单操作单保存契约。日期映射现有 date 类型；签名及不符合既有字段契约的候选明确跳过。最多扫描 300 个源候选，无 OCR、AI 或 provider。检测与关闭均不保存。模块仅在首次点击时动态加载。

## 原图像素裁剪与去背景（2026-11-13）

固定源ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的完整 apps/pdf/src/renderer/ImageDialogs.tsx：upstream SHA256 06d8817da3638e31b136ce968bf50ddf2d67750b5a4ed2f5402f58ecfab0cf3e；本地 SHA256 84ad4579027a4c0696042fa2bffe2bccb69084e65cadf27a8fe03817851faadf。本地仅在 CropDialog 增加四个键盘百分比输入，直接复用源crop状态；CutoutDialog保留原容差、预览、背景采样和像素处理。现有cutout.ts、image-bake.ts与Apache-2.0 LICENSE/NOTICE继续适用。

pdf-image-dialogs.ts/css是本地浏览器顶层dialog、中文词条、焦点返回与低高度样式适配。pdf-existing-image.ts在授权源/页面/图像指纹下读取对象自身像素，回调再次核对草稿和目标；取消、选择变化、销毁与迟到读取不提交。确认仅走既有transformExistingImage PNG替换与cropRect。服务器校验PNG实际身份和尺寸，不采用页面截图作为源图像。

本轮键盘适配另加 defaultPrevented/isComposing/keyCode229 保护；取消按钮 Enter 保留原生激活，不误应用裁剪。修正后本地摘要见本节，源摘要不变。

## 完整水印与页眉页脚对话框（2026-11-13）

固定源 ref f8c17004fb730df11f0f743164ffd8b4281bb38c，完整复用 apps/pdf/src/renderer/StampDialog.tsx、modal-dialog.ts、ColorPicker.tsx、color-presets.ts，现有 Apache-2.0 LICENSE/NOTICE 适用。

| 文件 | 上游 SHA256 | 本地 SHA256 |
|---|---|---|
| StampDialog.tsx | e2a5bcae03405410338a76812f829b66d6302a4349517e32543f97e806703aaa | 41044fa1d354c442f0404db51a3d9cf3fcf0509baf31bcb110362629284c5dbd |
| modal-dialog.ts | 4e222f3735f2c50d03de4bc0a4fd9f6258803d03bd6addb404e9ddb82adccb48 | bde76c5ebc474756603623ece65052a221d30e04682a4bfd50f8402b9de5df21 |
| ColorPicker.tsx | c1a201afcb05f6493d9720bd27b23e41ed32fed326c73b9bea1766592c30c55c | 80d7a7888e6a0e247642716286160140770cad6d5ef75e15fc86f6b277f31e05 |
| color-presets.ts | 84e6d58ef3d2a0a0e1c268f8ddd06a685c276f2849cff96bb328762554578d96 | 84e6d58ef3d2a0a0e1c268f8ddd06a685c276f2849cff96bb328762554578d96 |

完整StampDialog增加initial草稿/clear/inline error及滑块无歧义aria-label，保留宿主200字符/起始页上限；modal和色板Escape补IME/已消费事件与焦点返回；ColorPicker接同源共享组件与中文词条，无桌面locale runtime。

pdf-stamp-dialog-source.ts/css 为中文、顶层浏览器 dialog、焦点约束及低高度滚动适配。pdf-stamp-dialog.ts 仅提交现有 setStamps，复用既有 PNG 生成和 PDF writer；取消、权限/来源/草稿变化、销毁与迟到加载不写入。已有草稿重开保留配置；清除只移除 setStamps。服务端和签发链路未改动。

## 完整测量标定对话框（2026-11-13）

固定ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的 apps/pdf/src/renderer/MeasureScaleDialog.tsx，源SHA256 be621bc5ec0240aee2ab5d1eb4413007f10348f1abfd6e6c220d97919bd86494。保留长度/单位/校准错误/确定取消完整控件，计算沿用同源measure.ts。补浏览器顶层dialog、中文、共享modal键盘/IME/焦点、异步提交busy与错误；避免双重dialog角色。pdf-measure-dialog.ts以来源/页/草稿快照拒绝过期提交，取消和迟到模块不写草稿。pdf-main.ts继续调用既有pdfMeasurementOperation；校准仅会话有效，各Line保存独立标签。原有ASCII单位限制明示保留。此节不替代本轮未完成的冻结浏览器验收。Apache-2.0 LICENSE/NOTICE继续适用。

## 只读数字签名面板（2026-11-13）

`renderer/SignaturesDialog.tsx` 从相同固定源逐字复制；`shared/ipc.ts` 仅追加 CertificateInfo/PdfSignatureProblem/PdfSignatureInfo 类型摘录。宿主 `pdf-digital-signatures[-source].ts` 绑定已保存来源 SHA、只读原生检查模型、页码定位与取消焦点恢复；CSS 沿源卡片/状态/证书链结构并使用现有主题与短屏边界。中文状态覆盖明确“需要留意/信任未建立”，不沿用源 warning 标签中的“有效”，不以服务端 TLS 根信任冒称文档 PKI 验证。未保存草稿与预览不沿用该已保存来源结论，空清单/读取失败分别解释。

SignaturesDialog 上游/本地一致 SHA-256：`f8aa8d53f4e57e3d3053778eae40bb857353e54f271a140f718e0db3872e35f6`。
