# PDF 草稿外观、逐页排列与 PPTX 文字链接验收（2026-11-11）

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批继续三域限定增量，不含 OCR。已完成下述技术专项，整体 PDF 对齐、完整内容/版式保真与生产上线验收仍未完成。未提交、部署或启用生产开关。

## 实现与范围

文字草稿：固定源本身存在草稿居中标签/开口 caret 与实际 PDF 中点起写/填充三角的差异。本批是本地一致性适配，不冒称补回固定源未实现的 UI。只改前端 measure/caret 分支：按实际两位舍入 Tm 和 PDF 顶点，经 viewport 映射到 SVG，保留原操作数据、透明命中和移动事务。字体为 9 单位并由矩阵缩放，关闭浏览器 kerning/ligatures；真实 Chromium 探针发现 SVG 属性形式被忽略，改用 CSS style 属性。原生 writer、AP 命令、BBox 不改。通用成功告警同步改为浏览器字体回退和页边风险，不再错误描述本地草稿仍居中。字体 ink/advance 未证明逐像素同源，不能从矩阵通过推断字体保真。详见 NATIVE_PDF_DRAFT_AP_APPEARANCE_ACCEPTANCE.md。

表单：固定 App.tsx 按 pageIndex 分组，本地旧路径却拒绝多页选区，现补齐“按页独立排列”。先完整核对全部目标身份与页面，再分组；对齐/同尺寸每页至少 2 个、分布每页至少 3 个，不足页完全保留，全部不足则拒绝。各页独立使用 CropBox、Rotation 和本页 anchor，不迁移控件或跨页统一坐标。只把矩形真正变化的 Widget 交给原生重绘。

专项发现原生 dirty 标记以字段为单位，可能连带重绘跳过页的共享字段兄弟；仅排列保存路径在正式重绘前隔离 AP 顶层字典，之后恢复未修改控件原 AP，单次 save(false)。写后逐原间接对象和 encoded 流复核，只有实际改动 Widget 的 Rect/AP 可不同；字段树、值、默认值、页面 Annots 和归属保持。新增孤立 AP/font 对象可能保留，不清理历史，也不宣称对象零增长。旧属性编辑保存路径保持。详见 NATIVE_PDF_FORM_MULTIPAGE_ARRANGEMENT_ACCEPTANCE.md。

转换：真实 PDF 提取已有 span.href，PPTX 映射却丢失链接。本批仅改 rebuild-pptx/text.ts、rebuild.ts，复用现有 TextRun 与 ensureRunLinkRels，保留 HTTP/HTTPS/mailto 及严格有效的内部页跳转；所有 slide 先创建，表格/脚注关系归属对应页。链接目标参与 run 合并条件，plain/不同目标不串联，合成列表标记和 TOC 页码不继承链接。危险 URI、无效页号不生成可点击关系。写明来源颜色及下划线状态；只覆盖文字 run 链接，图片/整页栅格链接和复杂任意动作未纳入。详见 NATIVE_PDF_PPTX_TEXT_LINKS_ACCEPTANCE.md。

## 冻结构建与来源

一次成功 Vite、一次 bridge bundle、一次 runtime package，均 exit0。376 个 JS 分块预算零超限，PDF main 249833 bytes，form controls 34757 bytes，未放宽预算。

- static：`/tmp/pdf-ap-arrange-links-static`，manifest SHA `8c79637a9733aeefbbd248d7754b9fcc9b0b898bf5144c2c81078eda83519451`。
- runtime：`/tmp/pdf-ap-arrange-links-runtime`，CLI SHA `a8a7eb04dd7d4396a2607024871075d1b8efdc63730df893cf057f50aa17e091`。
- 45 个前端文件、191 个引擎/清单文件、955 个实际 bundle inputs 最终核验匹配；LOCAL 186 项、converter 48 项本地 hash 和 69 个固定上游 Git blob 逐项匹配。运行包来源/许可、三转换引擎通告、两个 WASM 身份匹配。
- 对上一批冻结输入的差异仅限本批指定的两个前端文件、四个引擎生产文件、相关测试及来源/清单；无依赖升级、共享 writer 重构或 XLSX 布局变更。

## 真实浏览器与实际产物

三条链路各运行一次并 exit0，各 37 个实际 JS 响应与同一冻结资源相符，三域集合及 SHA 完全相同；来源不变，asset/page/console/HTTP errors 为空。真实 grant、cookie、CSRF、生产资产、packed engine、预览确认、签发下载；文字和表单还覆盖保存后重开。持久化仓储仍是内存 fixture，不能冒称生产持久化/权限/网络验收。各 smoke 在保存或转换后持久化检查点，避免后续 verifier 失败丢失已完成步骤证据。

文字 `/tmp/pdf-ap-arrange-links-text-browser`：真实 0° 页面在 zoom 0.5/2/1 核对两条测量标签 SVG 矩阵与 caret 闭合填充顶点、computed kerning/ligature CSS、draft operations 不变，最后回 1x 保存。下载 mixed.pdf 14434 bytes，SHA `f10f2ca10f317129b8f90e032e31fb27802f870108253c65a3684d3c6fbea5d8`。独立 pypdf 将实际下载 AP Tm/顶点与浏览器 checkpoint 逐项比较通过；扩大 BBox 诊断副本与实际 PDF 渲染差 0 像素只证明 PDF 标签未裁切，不等于 SVG/PDF 字形像素同源。root 已目视 1x 草稿和实际渲染。0/90/180/270°、非零 CropBox、UserUnit2 的矩阵覆盖来自单测，不冒称浏览器全部覆盖。

表单 `/tmp/pdf-ap-arrange-links-form-browser`：五次创建、逐页 left 和 sameSize 共 7 次预览确认、保存、下载和重开，revision 4→11。left 实际 10643 bytes，SHA `181f9212f103e530e73801d5400d0ce4ceb09c1de79db8b20dbe61f5ff6a2343`；sameSize 实际 11520 bytes，SHA `274214dcc898bb748f4b20a86a4616cdf7950aa8ab1e9381b6d4341b6298e17d`。独立 pypdf 分别核 47/50 个原对象，实际变化 Widget 各 2 个，跳过页、原流、字段树及页归属保持。root 已目视最终三页；窄 singleton 原有长文本裁切仍保留，不把保持原样说成溢出已修复。

PPTX `/tmp/pdf-ap-arrange-links-pptx-browser`：实际来源 SHA `a90ba465c476290b8490621ff94a428096daffde110c1372b94c3236c374d57c`，下载 9458 bytes，SHA `01cf7d6b0be8a8d5df406adb27480dfee3169831c5808dede1aeb04d87837d93`。独立 ZIP 核 6 条链接（含表格和双向 GoTo）、三页、rId/Target/TargetMode、原显式字体/颜色/下划线及无非法 URI 关系。

对该实际下载仅执行一次 Impress 打开并导出 PDF（profile/output 在 /dev/shm），exit0，有非 fatal javaldx 警告。实际 rendered.pdf 18605 bytes，SHA `d223298a323bce4525a35e6b22987b44896f94b221cc3388608235d7a01922cd`；独立宿主复读确认 3 页和全部 6 个正确链接目标，root 已目视全部三页。

**实际宿主色彩保真未通过**：来源 Table link 与 Table plain 均为 #123456，PPTX table run 也明确写 sz=1200、u=none、solidFill=#123456；但 Impress 将 Table link 显示为主题 hlink 的 #0563C1，plain 及正文链接仍为 #123456。主题 hlink 本身恰为 #0563C1，证据指向宿主表格链接样式覆盖，尚未跟踪宿主内部函数。未改全局 theme 掩盖问题，不把链接可用误报为颜色保真。PPTX 首行约 +6.350708 pt 基线偏差仍未解决，overallFidelityPassed=false。

## 专项、复审与非阻断

- 文字新矩阵/caret 40 项真实 RED→GREEN，追加真实 Chromium CSS 探针后新 CSS 回归 RED→GREEN，最终 41 项通过；受影响旧渲染/移动事务 3 项通过。窄 strict tsc 通过。成功告警定向 native 1 项真实 RED→GREEN；一次错误相对路径只运行了旧断言，不记作 RED，真实失败证据为 `/tmp/pdf-next-draft-warning-real-red.log`。
- 表单 native 6 项、UI 3 项分批通过。保存分支改变后只复验受影响原 3 项；共享字段 AP 原位变异有真实失败证据。交叉审阅发现跳过单例页缺少页面元数据仍可暂存，新增独立 RED→GREEN，现分组前检查所有目标页面。未运行完整套件。
- PPTX 首批 5 项中 4 个缺陷用例真实 RED、负例原已通过，实现后 5 项通过；列表/TOC 范围追加 1 项 RED→GREEN。生产两文件窄 strict tsc 通过，测试入口仅记录既有 wasm-path/resourcesPath 诊断，不冒称完整 typecheck 通过。10 种独立 verifier 变异被拒绝。
- HTTP 新逐页排列故障、实际链接转换 review 故障、受影响测量软告警及签发静态守卫，最终 4 项通过，日志 `/tmp/pdf-ap-arrange-links-http-green.log`。旧运行包的排列/链接断言均真实失败。链接 fixture 首次漏导入 PdfReader，修 fixture 后仅重试失败一项；不算生产 RED，保留两个日志。首次宽选择器还执行了旧 DOCX/XLSX review 两项并通过，未再重复。
- 没有新增 Python 生产签发函数；新增排列后置审核覆盖已登记 test_http_publication_lineage.py。实际生成且身份可读取时，具体失败进入 validation/issues 并继续签发；所有浏览器保存/转换仍 validation=false，不冒称业务或完整版式验收通过。
- 三域只读交叉复审完成。最终哈希/结构复读与范围内 diff 检查通过。未重复完整项目测试，未重做已通过的上一批 browser/Calc，未使用 OCR。

总证据 `/tmp/pdf-ap-arrange-links-final-evidence-20261111.json`。继续开放完整游标/自动段落和跨对象 reflow、任意混合编辑、字体逐像素及页边保真、复杂表单/XFA/签名、完整 Office/MD/HTML 保真、XLSX 字体/MDW 与二维图文分页、PPTX 首基线及宿主表格链接颜色，以及完整生产镜像/真实权限/部署验收。
