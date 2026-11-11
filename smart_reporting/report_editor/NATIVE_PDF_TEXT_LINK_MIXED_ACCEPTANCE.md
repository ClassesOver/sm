# PDF 样式改字与安全新增链接同批验收（2026-11-11）

## 最小范围与固定源

固定 GenOffice 源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用 `apps/pdf/src/main/save-pdf.ts:470–501` 的 `addLinkAnnot`，在既有 styled replaceText + markup + vector + PNG 路径中接纳新增 `shape:link`。没有修改共享 writer、解码器、pdf-main 接线或 public operation 字段。无 OCR，不包含已有链接编辑/删除、复杂文字对象、任意 PDF 动作或链接外观设计。

固定 writer 输出 Type Annot/Subtype Link、两位小数 Rect、F=4、实际页面 P 引用；外链为 A `{Type:Action,S:URI,URI:PDFString}`，内部跳页为 Dest `[actual page.ref /XYZ null null null]`，没有 AP。沿用 UI 的 url/destPage 二选一，destPage 为不可变来源页表的 1-based 页码；混合路径仍拒绝页面删除、插入或重排，因此不增加新的目标身份 public 字段。

## 写前边界

仅新 styled mixed 链接路径执行 `mixed-links.ts` 的严格 URL 检查：最长 2048 个可打印 ASCII 字符；HTTP/HTTPS 必须可被 URL 解析且有 hostname，拒绝账号、密码及显式空 userinfo；mailto 必须有非空 pathname 且没有 fragment。协议、目标二选一、Rect、来源 SHA/pageId、原有页表目标范围及额外 payload 都在两阶段 writer 前检查。URL 保留原值写入，不做隐式重写。

拒绝原始空白/控制/非 ASCII、损坏百分编码，以及百分解码后的 Cc/Cf 控制字符，包括编码 CR/LF。允许合法 percent-encoded UTF-8 路径；原始中文/emoji 必须先百分编码。真实最小 PDFString 保存复读确认：raw 中文路径变为 `-⁄`，emoji 变为 `=\u0000`，编码中文原样保持；因此这项限制在写前生效，避免留到后置告警才发现 URI 已损坏。共享旧链接入口行为不在本批改动范围内。

继续拒绝加密/Perms/AcroForm，受影响页 UserUnit 必须为 1；新增链接目标及其他几何仍须在来源 CropBox 内。内部目标必须存在于当前来源页表，输出复核实际目标页 Ref；保存后页数及页 Ref 顺序须保持。

仅当本批包含新增 link 时，另外拒绝已识别来源动作边界：catalog OpenAction/AA、Names 字典自有 JavaScript key、page AA、任一来源 annotation A/AA/Dest。损坏 Names 的 typed lookup 失败按现有 fail-closed 处理；不因无关 Names 或空 EmbeddedFiles 名称树拒绝保存。现有来源批注字典和全部 AP 资源图的有界检查继续适用，未增加另一个主动内容 walker。

这些是本路径可证实的列举支持边界，不是整份 PDF 所有主动内容的穷尽清洗保证；包含既有链接或其他来源动作的文档不在本次可验证混合来源范围内。

## 输出复核及产物保留

新增 Link 严格核对 Type/Subtype、F/P、Rect 和字典白名单。外链仅允许 A，不允许 Dest；A 仅允许 Type/S/URI，必须恰为 Action/URI 和与请求逐字相同的 PDFString。内部仅允许 Dest，不允许 A；Dest 必须为目标实际 page.ref、XYZ 和三个 null。额外 AA、Next、JavaScript、AP 或其他字典项均使复核失败。Link 不纳入未支持它的 saved drawing census，单独复核后继续；不改变既有 Stamp 删除语义。

继续核对每页 annotation 槽位总数、来源引用/字典/AP 资源闭包；闭包预算为每个 AP 4096 节点、64 层并有 visited 防环。旧 AP 原始编码身份比较仍以 `styled.bytes → append 最终 bytes` 为基线，不声称跨 PDFium 阶段压缩字节不变。

append writer 或后置复核异常保留实际生成 bytes/SHA/size、样式改字既有决策和输入原索引；本批 additions 返回 `pdf_text_drawing_*_failed_generated_bytes_retained` 或相应 markup 告警，不冒称通过。root 统一负责 HTTP 签发及故障登记，验收失败不阻止已核验身份 PDF 的链接签发。

## 定向证据

- 初轮 native 5 项中 3 项因旧 shape 排他规则真实 RED；最小接线后，URL 凭据、来源 catalog AA、输出 URI 变化各自再次真实 RED。补 helper 后核心 5/5 PASS；日志 `/tmp/pdf-next-link-mixed-red.log`、`/tmp/pdf-next-link-guards-red.log`、`/tmp/pdf-next-link-mixed-green.log`。
- 核心覆盖真实 HTTPS/mailto/内部实际 Ref、旋转页、styled 多行、underline、原 operation indices/pendingMarkupMapping、其他页正文和 previewDigest；unsafe 协议、编码 CRLF/C0/Cf、凭据、无效目标/几何/额外 payload/来源摘要先于 native SaveAsCopy 拒绝，writes=0。
- 来源 catalog OpenAction/AA、page AA、annotation A/AA/Dest、Perms/AcroForm、other-page UserUnit 的写前拒绝通过。输出 URI/Next/AA/JavaScript/Dest/Rect/AP 共 7 类故障按原 additions 索引告警，实际 bytes/SHA 保留且原下载内容仍为正确链接；append writer 故障保留已生成 styled bytes。
- 空 userinfo 与 raw Unicode 预检分别真实 RED→GREEN，新增 2/2 PASS；同批真实保存 percent-encoded 中文 URI 正例。日志 `/tmp/pdf-next-link-userinfo-red.log`、`/tmp/pdf-next-link-unicode-red.log`、`/tmp/pdf-next-link-uri-green.log`。真实 PDFString 序列化探针 `/tmp/pdf-next-link-uri-writer-probe.log`。
- 交叉审阅补 catalog Names/JavaScript，独立专项真实 RED→GREEN，1/1 PASS，并验证普通空 EmbeddedFiles 名称树仍可保存 5 项混合操作；日志 `/tmp/pdf-next-link-document-js-red.log`、`/tmp/pdf-next-link-document-js-green.log`。
- 新 native 文件共 8 项按受影响阶段验证为核心 5 + URI 2 + Names 1；未在后续局部修改后重复整文件或全项目测试。
- 前端新路径先因 shape 排他真实 RED；接线后危险 URL 未拒绝再次真实 RED；空 userinfo/raw Unicode 两项也分别真实 RED。最后新 UI 4/4 PASS，含草稿不变、外链/内部目标、跨来源目标拒绝、边界负例和 percent UTF8 正例；日志 `/tmp/pdf-next-link-mixed-ui-red.log`、`/tmp/pdf-next-link-guards-ui-red.log`、`/tmp/pdf-next-link-userinfo-ui-red.log`、`/tmp/pdf-next-link-unicode-ui-red.log`、`/tmp/pdf-next-link-ui-uri-green.log`。
- 前端与新 helper strict scoped tsc 通过，日志 `/tmp/pdf-next-link-ui-typecheck-final.log`、`/tmp/pdf-next-link-helper-typecheck-final.log`。新 native 入口闭包仍有既有 operations 后段 union、Electron resourcesPath、缺失 GenOffice UI 类型诊断，见 `/tmp/pdf-next-link-typecheck.log`；新 mixed helper/测试无诊断，不标记全项目 typecheck 通过。
- smoke 的 node --check、独立 verifier 的 Python compile、定向 git diff --check 通过。未自行 Vite/bundle/package、提交或部署。

## 浏览器交付入口

`frontend/smoke/pdf-text-link-mixed-smoke.mjs` 使用统一冻结 static/runtime 的真实 PDF.js、grant/cookie/CSRF、packed engine、publication/download/reopen；仅 fixture 持久化仓储为内存实现。真实 pointer 拖出范围与原生“添加链接”dialog依次完成 HTTPS、AA/BB/CC 选区样式、underline、内部第 2 页跳转、mailto，核对 5 项交错操作、Undo/Redo、预览确认、下载 SHA 和重开。

独立 `frontend/smoke/pdf-text-link-mixed-verify.py <directory>` 以 pypdf 复核实际下载文件中的字体/字号/基线/嵌入字体、标注、其他页正文与页面框/旋转，以及三个 Link 的严格 A/Dest、实际页面 Ref、Rect/P/F、XYZ/null 和无额外 AP/AA。验证 PDF 结构与目标，不把本批描述为已实现编辑器内保存链接的点击导航。

环境：`PDF_SMOKE_STATIC_DIRECTORY`、`AGENT_REPORTING_PDF_ENGINE_DIR`、`REPORT_EDITOR_CHROMIUM_EXECUTABLE`、`PDF_TEXT_LINK_MIXED_SMOKE_DIRECTORY`，可选 `PDF_TEXT_LINK_MIXED_SMOKE_PORT`（默认 4340）。统一运行包真实 browser 已 exit 0，证据 `/tmp/pdf-link-radio-decimal-link-browser/summary.json`；37 个实际 JS 响应匹配冻结资源，来源未变、错误列表为空。实际下载 `mixed.pdf` SHA-256 `b2dd5107cadc37375cd58426fe9c68cab1c7d869d9e7a65fab2a0953b24cb178`，独立 verifier 通过，最终 UI 已目视。外链、内部目标及 writer 故障三项 HTTP 非阻断检查通过；完整统一证据见 `NATIVE_PDF_LINK_RADIO_DECIMAL_ACCEPTANCE.md`。
