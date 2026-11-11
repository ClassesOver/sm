# PDF 样式改字与测量/插入符号同批验收（2026-11-11）

## 范围和来源事实

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批仅把 measure/caret 纳入既有 styled replaceText + 新增文字标注/绘图混合保存；复用 `apps/pdf/src/main/save-pdf.ts` 的 `addDrawing`，没有修改公共 writer、pdf-main/native-api、public operation 字段或解码器。不含 OCR、已有图形变换、任意混合编辑、复杂文字对象或视觉一致性重设计。

固定 caret writer（679–709）输出 Caret 批注、point±10 的 Rect，AP 为 tip(x,y)→(x−8,y−6)→(x+8,y−6) 的填充三角；不使用传入线宽、没有 BS/Font/Resources。固定 measure writer（771–841）输出 Line/L/Contents/BS.W，AP 为主线和 Helvetica 9pt 标签，标签基点在线段中点的 y+6，倾角翻转为从左到右。F1 必须通过 AP Resources/Font 的实际间接引用解析为 Type1/Helvetica/WinAnsiEncoding；label 的括号与反斜杠按固定 writer 转义。真实 writer 探针见 `/tmp/pdf-next-measure-caret-writer-probe.log`。

仍保留上游视觉差异：Web caret 是固定 CSS 像素、1.5px 描边开口 chevron，PDF 是 PDF 单位的填充三角；Web 测量标签居中并按显示线条角度旋转、字号至少 9px，固定源原 UI 另有水平标签差异，PDF 标签从中点起写且随页旋转。measure Rect/BBox 沿用固定 writer 的 `label.length×4.5` 近似半宽与 `width+2` pad。本批没有用经验常数修正共享 writer，也不声称 UI/AP 视觉全等。

## 输入、输出和非阻断契约

输入继续 source SHA/pageId/受影响页 UserUnit=1/无加密、Perms 或 AcroForm、安全来源批注及完整 AP 闭包检查。measure 只接 from/to/label：端点在来源 CropBox 内、线长至少 2pt、非空且非纯空白的 1–64 可打印 ASCII 标签；caret 只接页面内有限 point。拒绝跨 shape 参数、链接/图片/签名元数据或其他额外字段；所有检查在两阶段 writer 前完成。caret 的 point 在页面边缘时其固定 ±10 Rect 仍可能伸出 CropBox，本批不扩大源 writer 的完整可见保证。

新 `mixed-measure-caret.ts` 严格复核批注字段白名单、Type/Subtype/F/P/C、Rect、AP 唯一 N/Form/XObject/BBox、缺失或精确单位 Matrix。caret 核对填充三角与无 BS/Resources；measure 核对 L/Contents/BS.W、固定路径/Tm/Tj、严格资源和真实 Helvetica 字典。解码 AP 直接用 `Buffer.equals(Buffer.from(expected,'ascii'))` 比较真实字节，不能通过 ASCII 解码屏蔽高位伪装操作符或标签。该验证不构造通用 PDF parser；独立 pypdf verifier 另按真实操作符和参数解析输出。

延续每页批注槽位数、原引用/字典/AP 资源闭包、原 operation indices 与 pendingMarkupMapping。AP 闭包仍限 4096 节点、64 层并有 visited 防环；原编码身份比较基线为 styled.bytes→append 最终 bytes。新增形状也经过现有保存绘图 census，未改变 Link/Stamp 的独立复核或已保存图形删除语义。

只有成功写入并通过本阶段复核的 measure 才返回现有通用 `reviewIssues`：原 operationIndex、kind=addDrawing、fieldName 为空、code=`pdf_measure_label_appearance_review_required`，具体提示固定标签从中点起写、BBox 按近似字宽估算、需核对完整性；纳入 previewDigest。沿用现有预览确认、消息渲染及 HTTP 转发，不新建告警系统。caret 无额外测量告警；writer/复核失败时不冒称 measure 已成功生成。

writer 或后置复核异常继续保留实际 bytes/SHA/size 和 styled 修改决策；本批 additions 按原索引返回 `pdf_text_drawing_*_failed_generated_bytes_retained` / 相应 markup 告警，不把验收失败冒称通过。HTTP 签发由统一链路核实，验收失败不丢实际产物。

## 实际渲染证据与未解决问题

独立 Poppler 144dpi 探针 `/tmp/pdf-next-measure-caret-visual/` 保存 actual.pdf/png 与 diagnostic expanded.pdf/png、diagnostic.json。诊断副本仅同时扩大 annotation Rect 和 AP BBox，保持 1:1 坐标映射，不修改 AP 内容或生产输出，两张均已目视：

| 实际固定 writer 场景 | 原图着色像素 | 扩大诊断副本 | 原 BBox 外缺失像素 |
|---|---:|---:|---:|
| 水平 160pt 线，`3.00 m` | 1371 | 1417 | 46，字顶裁切 |
| 水平 2pt 短线，24 个 W 标签 | 277 | 1443 | 1166，字顶及右端裁切 |
| 斜线 `(80,80)→(300,150)`，`3.00 m` | 1820 | 1820 | 0 |

这明确证明水平/长标签问题是当前固定 writer 的真实输出缺口；AP 内容存在不代表标签完整显示。问题保留为未解决视觉边界，通过通用软告警提示用户人工核对，没有通过改变 Rect/BBox 掩盖生产缺陷。斜线 fixture 的完整显示结论只适用于已验收几何，不推广为任意标签/任意端点保证。

## 定向验证

- 新 native 核心 5 项初轮因旧 shape 排他真实 RED（3 failed），最小接入后 5/5 GREEN：`/tmp/pdf-next-measure-caret-red.log`、`/tmp/pdf-next-measure-caret-green.log`。覆盖右到左与垂直标签/括号反斜杠、真实资源/字体/Tm/Contents、旋转页 caret、原索引/mapping、其他页正文、digest 重现，输入写前拒绝、Perms/AcroForm/UserUnit/悬空 AP 闭包拒绝，写前 SaveAsCopy=0。
- 10 类字体/资源/Contents/measure path/caret fill/caret path/Matrix/Rect/额外动作故障均返回原 additions 告警并保留实际最终字节；append 故障保留已生成 styled bytes，未提交或重构共享 writer。
- measure 通用软告警单项真实 RED→GREEN，核对成功原 indices0/4、后置复核失败 reviewIssues=[]，1/1 PASS：`/tmp/pdf-next-measure-caret-warning-red.log`、`/tmp/pdf-next-measure-caret-warning-green.log`。
- 交叉审阅发现 ASCII 解码会清高位；新 operator/label 高位故障先真实 RED（误认为 additions 已通过），改真实字节比较后 1/1 PASS：`/tmp/pdf-next-measure-caret-bytes-red.log`、`/tmp/pdf-next-measure-caret-bytes-green.log`。新 native 共 7 项按核心5+告警1+高位1受影响阶段验证，未重复全文件或全量项目测试。
- 新 UI 先真实 RED 后 2/2 GREEN，包含两种次序、草稿不变、measure/caret 几何/标签/额外参数/过期源：`/tmp/pdf-next-measure-caret-ui-red.log`、`/tmp/pdf-next-measure-caret-ui-green.log`。helper 与 UI scoped strict tsc 通过：`/tmp/pdf-next-measure-caret-helper-typecheck.log`、`/tmp/pdf-next-measure-caret-ui-typecheck.log`。不声称全项目 typecheck 通过。
- 独立 native fixture `/tmp/pdf-next-measure-caret-independent-native/independent.json` 真实 mixed 5ops 与同源浏览器 source_pdf：pypdf 字体/标注/资源/几何通过，两条斜线标签实际渲染与等比例扩大诊断副本差 0 像素。

## 冻结浏览器验收

入口 `frontend/smoke/pdf-text-measure-caret-mixed-smoke.mjs`；独立 verifier `frontend/smoke/pdf-text-measure-caret-mixed-verify.py verify <directory>`。使用真实冻结生产资源、PDF.js、grant/cookie/CSRF、packed engine、预览确认、保存签发/下载/重开；仅 fixture 持久化仓储为内存实现。UI 真实 pointer 参考线标定 3m、AA/BB/CC 选区样式、underline、caret 点击及会话比例下 1.50m 斜线，验证 5 项交错操作、Undo/Redo、两项原索引软告警和确认保存。

环境：`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_MEASURE_CARET_MIXED_SMOKE_DIRECTORY`；可选 `PDF_TEXT_MEASURE_CARET_MIXED_SMOKE_PORT` 默认 4341。root 使用端口 4359 完成统一浏览器运行；已读取 `/tmp/pdf-measure-radio-currency-text-browser/summary.json`，ok=true，37 个 JS 响应与同一冻结 static SHA 一致，来源未变且 page/console/http/asset errors 均为空。实际下载 SHA-256 `34d2b2910c9896d1e2117794fde959c119db86128a8aab335ee8cd66ee6b6be8`。独立 pypdf/Poppler 确认字体/基线、Helvetica 9pt 标签、caret 填充/其他页，600×800 的实际与扩大诊断副本差 0 像素；实际下载渲染已目视，两条斜线标签完整可读。

smoke SHA-256 `48e7d663719067a17cb9e7c79638c194464383675b778d87ae42ec69e2f7438e`；verifier SHA-256 `c8486b7c1a06e1fbc1fd86d49fc86646d60815205c1a961540fb10d0fa1d6261`。node --check/Python compile 已通过；Pillow getdata 发出非阻断弃用提示，本批冻结后未改 verifier。统一 runtime/static 身份与 HTTP故障项由 root 统一验收记录收口。

## 统一HTTP与身份收尾

真实HTTP测量线/caret后置故障3项、radio删除故障1项通过；真实测量线成功告警1项与首次签发静态守卫1项通过，共6个唯一检查。首轮告警测试漏sourceSha256导致422，仅修fixture后重跑失败1项；已通过的其他项没有重跑。45前端、184引擎/清单和954 bundle inputs最终无漂移，375个JS分块预算零超限。AP高位字节复核修复已进入实际runtime。IPC既有来源清单误记已纠正，代码与CLI不变；69个固定Git blob核验匹配。统一范围与剩余边界见 `NATIVE_PDF_MEASURE_RADIO_CURRENCY_ACCEPTANCE.md`，总证据 `/tmp/pdf-measure-radio-currency-final-evidence-20261111.json`。
