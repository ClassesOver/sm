# PDF 文本字段溢出软告警验收（2026-11-11）

## 范围与证据边界

本批处理上一批实际复现的裁切风险：120pt 控件使用 Courier-BoldOblique18 时，`Alice Updated` 文宽140.4pt，而 border/padding 后可用116pt，右对齐文字起点为-22.4pt，左侧24.4pt处于AP clip之外。当前目标是解释风险并保留实际修改，不自动缩字号、不静默换字体、不拒绝写入或下载。本批不含OCR。

`src/main/form-text-properties.ts::inspectFormTextOverflow(document,fieldName)` 只检查既有白名单内的ASCII、独立文本Widget、已证实DA/AP一致的标准Latin字体。多Widget、自定义/CJK字体、密码/富文本/动作等仍保持原检查边界，不以未测量冒称没有风险。测量使用独立临时PDFDocument的同一StandardFonts字型，绝不向被检文档注册对象或更改AP。

布局直接调用pdf-lib既有 `layoutSinglelineText` 或 `layoutMultilineText`，控件旋转、borderWidth+1pt padding及可用bounds与pdf-lib默认文本外观provider一致，0.01pt容差仅过滤浮点噪声。单行与多行分别判断实际layout行范围是否越过clip bounds；多行会先由原库换行，不能把完整字符串宽度直接当作多行宽度。本批不实现自己的排版器，不证明自定义外观、非标准字型或任意阅读器的完整视觉等价性。

## 回执与消费者契约

溢出返回独立 `reviewIssues` 项：`{operationIndex,kind,code:'pdf_form_text_overflow',fieldName,message,details}`。details包含singleline/multiline模式、fontName/fontSize、可用宽高、实际layout宽高与横向/纵向溢出标志。原 `appliedOperationIndices`、`skippedOperations` 与生成bytes/SHA保持真实；已经应用的修改不伪装为skipped。复核测量意外失败仅增加 `pdf_form_text_overflow_review_failed`，保留已识别文件。

属性修改由 `bridge/form-text-properties.ts` 在实际输出上调用helper，并把reviewIssues绑定previewDigest。后续 `setFormValue` 由root在operations最终bytes上检查并映射原operationIndex/kind，测量异常独立兜底。Python/API/前端预览及发布消费者由root统一接入；这些公共消费者和签发下载的最终验收不由子任务单元测试代替。

## 专项验证

新增 `bridge/form-text-overflow.test.ts`：先四项真实RED（缺少helper/属性回执reviewIssues），最小实现后4/4 PASS：

- 单行Courier-BoldOblique18实测140.4pt/116pt横向风险，校验不改变被检文档任何间接对象。
- 同字符串多行由库真实换行，宽度75.6pt，改为高度风险；加高80pt后没有溢出告警。
- 可放下、空值字段没有告警；custom字型不进入已证明标准字体测量范围。
- 属性修改实际applied[0]/skips[]/bytes身份保持，独立reviewIssues表达风险。

新增全桥后续填值与后置测量故障两项先RED（实际写入成功但reviewIssues缺失），root接好消费者后2/2 PASS。另一个定向属性路径测量故障注入PASS：实际Courier字型、字号18、值及文件身份保留，只追加review_failed。没有重复完整测试。日志：`/tmp/pdf-next-form-fonts/overflow-{red,green,fill-red,fill-green,property-fault-green}.log`。纯读模块strict TypeScript检查通过，`overflow-types-green.log`；最初mode被推断string的类型诊断已修正为显式联合类型。

## 独立字节与浏览器交接

为确认新独立verifier可运行，按原生桥实际顺序生成name/code两个字段，再修改单行字体/字号、切换多行、实际填值，输出位于 `/tmp/pdf-next-form-fonts/overflow-independent`。native.log显示三次风险修改均为applied[0]/skips[]，单行宽140.4/116，多行布局高度31.1256/20，后续填值布局高度48.1032/20。独立pypdf verifier检查实际AP/DA字型字号颜色、原值/字段引用、无关code字段/AP、三页正文/几何与实际单行-22.4pt起点、多行多个Tm，`independent.json`的ok=true。

新真实链脚本 `frontend/smoke/pdf-form-text-overflow-smoke.mjs`，配套 `pdf-form-text-overflow-verify.py`，使用 `PDF_FORM_TEXT_OVERFLOW_SMOKE_DIRECTORY` / `PORT`（默认4343）及root统一冻结的静态/runtime目录。预期覆盖属性单行风险→多行高度风险→后续填值风险，每次查看实际PDF预览、保存告警、真实下载与重开。填值风险预览不勾选确认仍可保存，以证明新软告警不变成阻断门禁；原有属性操作的确认边界保持。静态syntax/compile检查已通过，初次交接时尚未运行统一production browser；最终summary及下载身份见下文。

## 统一冻结后的实际浏览器与非阻断结果

root 完成 `/tmp/pdf-three-increment-form-browser/{summary,independent}.json`：单行属性宽溢出、多行属性高溢出、后续填值高溢出均显示独立告警，applied[0]/skips[] 保持真实；填写风险预览未勾确认仍成功保存。五次实际下载/重开、字段树值与 Widget/AP、Courier-BoldOblique18、黑色、无关字段 AP/引用和正文独立核验通过。最终填值 PDF SHA-256 `62123ae6e82f7670a65d74e5d6f0d8819011d1a282b36c47610359c96c817841`。37 个实际 JS 响应与冻结 static 一致，来源保持，page/console/HTTP/asset errors 为空；风险预览及实际裁切已目视，未将显示裁切当作已修自动适配。

Python preview/publication 接入独立 reviewIssues；setFormValue 进入回执路径但不增加确认门禁。新增 pdf_review_issues 对缺键、null、非列表元数据返回明确 `native_pdf_review_issues_invalid` 告警，继续签发实际生成文件，已登记 `_SIGNING_CHAIN`。HTTP 正常溢出、测量故障及三个元数据损坏场景均有定向证据；新增损坏场景先 RED 后 GREEN。前端 host 新两个行为用例先 RED 后 GREEN：属性风险显示且可确认，普通填写手动校验可看实际风险预览且不把填写标为 skipped。统一身份见 `NATIVE_PDF_DRAWING_OVERFLOW_ORIGIN_ACCEPTANCE.md`。

测量结论只覆盖 pdf-lib 布局位置与 advance 范围；单行高度使用库的 ascender 布局，不是完整 glyph ink bbox。斜体左右外伸、部分下伸字形、复杂 AP 和任意阅读器裁切不能据此排除。未返回告警不代表完整视觉验收通过，仍需实际预览；本轮不新增字体度量补偿或自动适配。
