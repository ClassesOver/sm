# PDF 转 PPTX 本地转换增量

2026-11-11。本记录覆盖本地转换桥与真实产物回读；HTTP、独立派生文档登记、授权下载、打包及真实浏览器接线由主线程统一验收，不因本记录自动视为通过。

## 复用与范围

- 固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，复用 `packages/pdf2docx/src/rebuild-pptx/index.ts` 的 `convertPdfToPptx`，共享 PDFium 提取→布局分析→IR→PPTX 绝对定位重建。不是纯文本另造转换器，不调用远程转换服务。
- 新增 `pdf_engine/vendor/pdf2docx` 为 41 文件、641252 原始字节的静态导入闭包，附 LICENSE/NOTICE；来源和本地 SHA 见 `SOURCE-SHA256.json`。仅三处 PPTX 引擎相对导入改为当前已有 `slides_engine/packages/pptx-engine`，详细见源包 `SOURCE.md`。
- 复用现有 PDFium 2.15.1、WASM、font-metrics 与幻灯片引擎；新增 PDF 引擎依赖 bidi-js 1.1.0，满足上游 `^1.0.3`。没有导入上游包总入口、DOCX/XLSX rebuild 或平台 `ocr-vision.ts`。
- OCR 明确禁用：没有供应 OCR 引擎或启动进程。扫描页保留上游图片回退与 `scanned` 状态，不宣称文字可编辑。DOCX/XLSX/MD/HTML 尚未实现，不能记为完整 Office 转换已对齐。

## 转换接口与产物语义

- `bridge/convert-office.ts` 导出 `convertPdfOffice(content: Uint8Array, request: unknown)`，严格请求 `{format:'pptx',sourceSha256}`。不接受 OCR、密码、任意本地路径或额外选项。
- 来源 SHA 与实际字节一致，最多 24 MiB、50 页。渲染比例 2，按 MediaBox/CropBox 最大尺寸及 UserUnit 检查单页 2000 万、合计 1 亿像素预算；受保护来源拒绝。表单/批注语义转换未保证，存在时明确告警。
- 返回实际 `bytes/sha256/size/sourceSha256/format/pages/warnings/pageResults/scannedDocument/validation`。`validation.ok` 始终 false，明确完整内容与版式保真尚需人工核对；能打开和页数相同只证明结构复核，不代表内容验收通过。
- 在实际生成字节后，结构复核失败会追加具体原因且保留实际字节；实际输出大于 64 MiB 同样返回字节并告警，不把后置复核失败写成阻断签发异常。父 PDF 不由此接口改写。

## 定向验证

- `/tmp/pdf-convert-office-red.log`：新增模块缺失的 RED。依赖安装期间首次 GREEN 无 tsx，未计通过；随后首次真实运行发现测试和后置复核误用 `OpenedPptx.slides`，已按既有接口修为 `OpenedPptx.deck.slides`。
- `/tmp/pdf-convert-office-final.log`：5 项 PASS，真实 PDFium/WASM 与固定源 writer；包括可编辑文字页、严格请求/保护来源拒绝、扫描图回退无 OCR、实际输出结构复核故障仍保留字节、页数与像素/UserUnit 预算。没有重复完整测试。
- `/tmp/pdf-convert-office-evidence/` 包含 source.pdf、converted.pptx、scanned.pptx、review-failed.pptx、receipt.json 与 independent.json。Python/python-pptx 独立读取 converted.pptx 为两页，标题 First/Second editable report 和附文均为可编辑文本框，页面400×300pt对应5080000×3810000 EMU；扫描结果为一页原图，图片覆盖页面全部几何且图像数据可读取。
- 故障注入仅替换现有 `PackageArchive.open`：识别实际生成的第二页内容后抛错，不影响空白源模板。调用仍返回实际 SHA/size 与具体失败 issue；恢复读取器后及独立 python-pptx 均能读取 review-failed.pptx 的两页正文。生产接口没有测试专用开关。
- 41 文件原始/本地哈希逐项重新核对通过；`git diff --check` 通过。局部验证未证明统一构建、生产部署、复杂多栏/表格/字体/旋转/交互语义的整体保真。

## CLI、Python 与派生发布接线

- `pdf_engine/bridge/cli.ts` 新增严格 `kind:'convertOffice'`，只接受 PPTX、source SHA、桥接器控制的 input/output 路径；输出使用 `wx` 不覆盖来源。`npm run bundle:bridges` 通过，日志 `/tmp/pdf-convert-cli-bundle.log`。
- `delivery/pdf_native.convert_pdf_office(content, output_format='pptx')` 返回真实 `content` 与身份。实际输出生成后若 CLI 状态/JSON 回执失败，或回执身份不匹配，会丢弃不可信转换元数据、保留读取到的实际文件与新算的 SHA/size，并返回明确失败原因。产物未生成或实际字节不可读时不能签发对应下载。
- `native_pdf_convert.convert_office(editor, context, expected_sha256, request_id, output_format='pptx')` 复用来源读取、workspace、repository.create_from_source 与 publication._publish_artifacts。产物为独立 PPTX derived document/revision1，绑定父 PDF 文档、修订和 SHA；`artifacts.pptx` 沿用现有协议，父 PDF 字节不变。
- 请求目录绑定原上下文、requestId、目标格式；文件名额外绑定实际输出 SHA，避免并发/重试的 ZIP 时间戳差异覆盖实际产物。不宣称相同请求跨时间重渲染完全字节一致；不同实际字节可以形成不同派生登记。
- 工作区写后回执异常继续核对实际文件；复核 helper 异常后直接重读实际字节与 SHA 可恢复。派生登记或持久下载副本保存失败均保留已核验实际文件与下载，validation 仍 false。大于24MiB文件仍可下载，未开放在线编辑。
- `/tmp/pdf-convert-service-red.log` 为模块不存在的 RED。沙箱内异步 workspace 首轮测试挂起，人工中断为exit130，不计通过；按环境权限机制重试后 `/tmp/pdf-convert-service-green-escalated.log` 为 **10 PASS**，9.63s，只有既有 imghdr 弃用警告。覆盖真实 dist CLI→python-pptx 三页可编辑正文、正常派生、注册失败、写后异常、复核失败、持久副本保存失败、非法参数和输出已写出的回执故障。
- 本段没有宣称 HTTP/真实浏览器已验收；该接线及签发静态守卫和HTTP故障登记由主线程记录。
- 目标格式编辑入口还受 `editor.is_enabled('pptx')` 控制：服务向发布器传入 `allow_editor`，PPTX 未启用时仍登记独立文档并签发实际文件下载，但不签发不可打开的编辑授权。新增 False/True 两项专项 `test_conversion_editor_link_respects_pptx_feature_switch_but_keeps_registered_download`；本子线程普通执行环境再次出现 AnyIO idle worker/event-loop wait，30秒线程诊断保存在 `/tmp/pdf-convert-editor-switch.log`，已中断exit130且不计通过，交主线程可用运行环境仅执行该新节点。
