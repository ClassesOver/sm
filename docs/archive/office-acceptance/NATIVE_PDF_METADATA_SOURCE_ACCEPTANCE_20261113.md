# PDF 文档属性四字段固定源接线与验收

固定源为 `/home/junge/pros/genoffice-source-full`，HEAD 已核实为
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮恢复时 metadata 产品及定向测试已在
worktree 中，旧 `/dev/shm/office-pdf-metadata-20261113` 已清空；不把已不存在的历史
RED、单测日志或浏览器证据冒充当前证据，也没有重新实现既有功能。

本轮证据根：`/dev/shm/office-current-state-pdf-metadata-20261113`。
`office-current-state-pdf-20261113` 是另一项 protection 证据，与本专项分开。

## 固定源行为与本地映射

- `apps/pdf/src/renderer/PropertiesDialog.tsx`：标题、作者、主题、关键词前四项可编辑；
  每次打开从 `pending?.field ?? rawInfo.Field ?? ''` 初始化，空字符串是有效待保存值。
  其余文件名、页数、大小、版本、生成工具与时间为只读。readOnly 时禁用四项输入，
  只保留关闭按钮；打开、取消不写内容。
- `App.tsx` 的 `PropertiesDialog.onApply` 关闭对话框后调用
  `applyEditOps([{op:'setMetadata',metadata:meta}])`。pending metadata 属于原编辑历史，
  保存传入原 `SavePdfRequest.metadata`，不是仅显示属性面板。
- `shared/ipc.ts::MetadataInput` 只含 `title/author/subject/keywords`；
  `main/save-pdf.ts::applyMetadata` 原样复用。标题、作者和主题不 trim，空串可清空；
  关键词按英文/中文逗号、英文/中文分号拆分、trim 和滤空，再由 pdf-lib 以空格写入。
  原函数会更新 ModDate。本轮按函数片段逐字比较固定源与本地，确认相同。

本地 `frontend/src/pdf-metadata.ts/.css` 提供 native dialog 适配；Home 的
`genoffice.pdf.home.properties.documentProperties` 打开四项编辑和其它属性只读信息。
确认后进入现有 NativeDraft 的一项 `setMetadata` 快照；再次编辑替换当前快照而不是
积累多份冲突属性，两个版本仍可分别 Undo/Redo。刷新从原修订身份绑定草稿恢复。
PDF 页面投影校验后跳过文档级操作，正常页序、旋转、便签等继续使用现有路径。

桥协议为 `{kind:'setMetadata',sourceSha256,modifiedMs,metadata:{四字段}}`。服务端校验
必需的不可变来源身份、完整字段、单份快照及类型；不接受 producer、creator 等额外
可写字段。本地上限为每字段4096字符且不接受控制字符。来源含签名、加密保护、动态
XFA 或无法确认能力时只可查看，现有独占编辑/重排版的组合边界继续保留。

`modifiedMs` 是本地确定性适配：将应用时刻留在不可变草稿，原 metadata 写入后将
ModDate 固定到该时刻（PDF 精度为秒），避免原函数使用每次当前时间造成 preview、
preview-file、save 身份无法复现。未修改固定源 writer。写后日期处理异常与属性复核
异常只进入 reviewIssues，保留实际文件；未另建工作区、发布路由或签发函数。
原确认/回执种类集合纳入 setMetadata，普通文字 feature 关闭也可用属性编辑。

不新增通用自定义 Info 编辑、XMP 编辑、字体样式或其它属性字段。

## 本轮必要修复与失败证据

首个 `browser-source/` 尝试在 apply-history 阶段失败，save 请求为0：Vite 冷优化/
配置重载打断对话框；静态宿主默认不允许跨目录符号链接，worker 产生404。根据
Starlette lookup_path 逻辑确认后，仅修验收 runner：复制约4MB PDF.js 运行资源和
单个 worker/图标，不复制 node_modules；读取 Vite 配置一次且预包含 react/jsx-runtime，
避免验收途中配置重启。没有改共享 Vite 配置或 static/dist。

第二个 `browser-source-second/` 到达实际预览阶段，HTTP 全200、无 browser/console
errors，但等待实际预览60秒失败，仍为0 save。现场定位到产品真实缺口：
`PDF_REVIEW_KINDS` 与服务端确认已纳入 setMetadata，而 `previewDraft` 的实际 PDF
加载白名单遗漏它；仅属性+旋转/重排时 preview API 成功后前端提前 return，无法确认。
`metadata-preview-missing-red.json` 记录缺失 guard 与修改前 main SHA。

产品修复只在该 guard 加入 `setMetadata`。最终同一完整 runner 进入实际预览并保存
成功，是该缺口的行为 RED→GREEN；没有为“通过”绕过确认、伪造回执或改测试预期。
本轮未重跑 Bates，也未跑/重复完整 suite。

## 当前定向服务契约

`service-current.log`、`service-current.exit-code`：
`test_native_pdf_metadata_service.py::test_metadata_review_warning_retains_actual_saved_download`
单项通过，退出0，19.14秒。使用真实源码桥和现有 NativeEditorService，仅身份/仓储
复用既有内存夹具。普通 text feature 关闭时可预览；缺少确认走既有确认契约。

确认后注入 `pdf_metadata_output_review_failed`，结果仍登记新修订、validation=false，
下载链接有效。实际下载经 pypdf 检查四字段与原 `Amount due 500` 正文，来源字节不变。
这是属性写后复核告警的非阻断证据，没有把告警改成验收通过。

已有 metadata 引擎4项、前端3项与历史相邻测试文件保留在仓库；本轮没有为补回丢失
日志重复执行它们，不把历史通过数计入本轮当前验证总数。runner node --check 与两个
Python smoke 文件 py_compile 均退出0，缓存写到本次 /dev/shm 目录。

## 真实源码 HTTP 完整链与独立下载回读

最终 `browser-source-final.log` / `.exit-code` 为0，证据在 `browser-source-final/`。
前端使用当前源码 Vite、引擎使用无 dist 的源码桥目录；真实授权 cookie、CSRF、
native 路由、预览文件、保存新修订、签发下载和新修订重开全部经过 HTTP。
仅身份/仓储使用现有内存夹具，尚不是最终生产冻结包验收。

流程：打开原四字段→改后取消不脏→填写标题/中文作者/清空主题/四种分隔关键词→
确认→Undo到空草稿→Redo→再次改标题→Undo回上次值→Redo→反序→到首个可见页
右旋→刷新恢复→打开确认待保存值→取消→请求实际 PDF preview/preview-file→勾选
确认→保存 rev4→5→点击实际下载→重开 rev5→再次打开属性确认实际保存值。

preview 的3项操作全部 applied，0 skipped、0 reviewIssues；浏览器、console、HTTP
errors 全空。前两次分别0 save，最终1 save；合计仅生成登记一次新修订。

源 PDF SHA：`224b76d103247e606dd409a5a5bac6f011b620ba343a611b47178065f5b54f0e`。
下载实际 PDF：1499 bytes，SHA
`ca73227b8638444ac05962559f79f80f3723f6a57e6b30f655f981baf72fac81`，与签发身份一致。

独立 Python 进程用 pypdf 读取相同下载，不复用 writer/运行时 inspector，确认：

| 属性/结构 | 实际结果 |
| --- | --- |
| Title | `合同 <更新> & 中文` |
| Author | `Alice & 张三` |
| Subject | 空字符串，原主题已清空 |
| Keywords | `alpha beta 中文 gamma` |
| ModDate | `D:20261113002750Z`，等于草稿 modifiedMs 的秒精度值 |
| Creator / Producer / CreationDate / CustomAudit | 与来源逐项相同 |
| 两页正文 | `Original metadata page 2`、`Original metadata page 1` |
| Rotate | `[90,0]` |
| 原书签 | 名称保留，目的页随重排从0到1 |
| 原附件 evidence.txt | 字节 `Preserved source attachment` 保留 |

源文件字节 SHA 未变化。独立结果为 `independent-verification.json`，原下载
`downloaded.pdf`、HTTP 请求 `http-evidence.json`、完整 API 结果 `evidence.json` 均保留。
保存结果仍 `validation.ok=false`，原因 `native_source_review_pending`，实际 PDF 下载
照常签发，不称业务事实或完整版式验收通过。

桌面1440×900、390×700窄屏顶部/滚动到底及新修订属性截图均实际目视。四字段与
只读信息可读，取消/确定可达；dialog width=scrollWidth=356、height666/scrollHeight744，
无横向溢出。窄屏按对话框纵向滚动，不靠正文滚动寻找确认按钮。

## 源码阶段冻结身份与边界

产品已通知 root 冻结；除 actual-preview guard 单点修复外，本轮只改验收 runner 和
专项记录，不触碰 protection 或共享构建。`source-identities.json` 记录10个当前产品/
源 writer 文件 SHA、4个固定源原文件 SHA 及 metadata writer 函数片段身份；最终
browser 记录的4个前端模块 SHA 与当前磁盘逐一一致。`reconciliation.json` 汇总本轮
失败、唯一完整保存、独立回读和非阻断证据。

等待 root 统一物理源码构建后，仅补最小冻结入口/实际加载资源 SHA 和必要视觉，
不重复完整保存下载。本轮不宣称签名/加密/XFA编辑、XMP同步、任意PDF复杂结构或
最终冻结静态包已验收；这些不是四字段源码链成功所能推出的结论。

## v2 统一冻结包最小续验（历史基线）

root 最终物理快照为
`/dev/shm/office-four-format-numbering-print-metadata-20261113-v2/source`，
使用其中 `smart_reporting/report_editor/static` 与
`smart_reporting/reporting/pdf_engine`，不回退到 Vite 或旧包。实际输入直接复用上述
源码完整链已签发下载的1499字节 PDF，SHA
`ca73227b8638444ac05962559f79f80f3723f6a57e6b30f655f981baf72fac81`；
只给 smoke 宿主/runner 增加 `PDF_METADATA_SOURCE_PDF` 和独立 pypdf 读取 baseline，
没有改产品或已冻结资产。

最终 manifest SHA：
`6e565b64b5d5dd5f549202d8552e4f03d994559b64d9bad62e2a9d10456163ef`。
`browser-frozen-v2.log` / `.exit-code` 为0，`PDF_METADATA_MINIMAL=1` 覆盖真实
入口、输入PDF四字段回读、取消、编辑、两轮Undo/Redo、重排旋转和刷新恢复，
savedRevisions=0，独立HTTP记录 save 请求为0。没有重复保存、下载或完整测试。

捕获108次实际同源静态资源200响应，54个不同文件，逐次响应 SHA=磁盘文件 SHA，
54个文件全部映射到该 manifest 的 file/css/assets。实际主入口
`assets/lazy-pdf-main-f-iqcq_M.js` 与 CSS 均在捕获列表中。10个本专项产品/writer
文件的当前磁盘、物理快照、SOURCE/BACKEND-SNAPSHOT-SHA256登记逐项相等；
minimal 记录的4个前端模块 SHA 也与上述身份相等。

PDF `dist/cli.mjs` SHA 为
`2e7f096fc521e260e3f76ea0da702ac252937321c48eb249bc24d087521afdef`，
与首轮成功桥构建一致；210个已登记 PDF 引擎源码文件逐一与首轮物理快照比较一致，
确认 v2 重用的是相同引擎源码与已成功构建字节。

实际HTML由已授权 `/reports/v1/native/...` 路由返回，不在静态 asset prefix 捕获范围。
因此另外只补一次浏览器 HTML 响应读取（JavaScript禁用，不再跑UI），最终响应200、
841字节，响应字节 SHA 与该冻结包 `native.html` 相等：
`f28f979529665646929b244c57ddc8aa2de02d81bd4c097a5645e52c74afc282`。
证据为 `html-entry/evidence.json` 与 `actual-native.html`，该读取也为0 save。

最终桌面、390px顶部与滚动到底截图重新实际目视，字段、只读信息与取消/确定可达，
dialog width=scrollWidth=356、height666/scrollHeight744，无横向溢出；browser、
console、HTTP errors 均为空。完整绑定为
`browser-frozen-v2/frozen-binding.json`，`reconciliation.json` 已更新分层状态。
业务验收继续保持源码真实保存时的 `native_source_review_pending` 失败，不因冻结
入口及资产身份通过改称业务事实或完整版式验收通过。

## v3 统一冻结包最小续验与时间作用域

v3 为 v2 基线叠加 XLSX 隐藏表修复，本专项只使用物理快照
`/dev/shm/office-four-format-numbering-print-metadata-20261113-v3/source` 中的
static、frontend 和 PDF engine。未采入 live 工作树并发出现的 PDF 拆分等新功能，
未覆盖其代码，也不将它们列入本专项已验收范围。源码完整链证据写入于
`2026-11-13T00:28:12.637854+00:00`，v2 最小续验证据写入于
`2026-11-13T00:35:45.007119+00:00`；前文“当前磁盘相同”只表示当时检查时刻，
不能外推为现在 live 工作树仍与冻结包相同。`source-identities.json` 保留原始时点记录。

v3 manifest SHA 为
`490aa9f5b482fe532ebd24d01b1479fe7b85f60a5dbaab6f7863486c79701444`。
`browser-frozen-v3.log` / `.exit-code` 为0；唯一一次 v3 最小运行继续复用源码链已下载
PDF，SHA `ca73227b8638444ac05962559f79f80f3723f6a57e6b30f655f981baf72fac81`。
只验入口、四字段、取消、编辑历史、旋转重排与刷新恢复，savedRevisions=0，
HTTP记录save请求=0；没有再次运行完整保存下载链或完整测试。

v3 smoke 直接捕获授权入口最终 HTML 响应，200、841字节，实际响应、保存的
`actual-native.html` 与物理 static/native.html SHA 全相同：
`800a9f2f9aea713245535d23fc443b8207c746ec42de0886908785b5e4997fea`。
108次实际静态资源响应覆盖54个不同文件，每次响应 SHA 均等于 v3 磁盘文件，
全部可映射该 manifest 的 file/css/assets。实际 PDF 主模块为
`assets/lazy-pdf-main-CL9pNEWu.js`。重建后入口和依赖 chunk 身份有变化，故按 v3
manifest 独立核对，不声称 v2/v3 静态构建字节整体相同。

10个本专项产品/writer 文件逐一与 v2物理快照、v3物理快照、v3源码登记和源码阶段
原始身份相等；pdf-view-ribbon.ts 也与 v2物理快照及v3登记相等。minimal 的
`identityFrontend` 明确指向 v3物理frontend，4个前端模块身份从该物理目录读取，
没有再读取漂移的 live 目录。210个已登记PDF引擎文件逐一与v2物理快照相等，
dist/cli.mjs SHA仍为
`2e7f096fc521e260e3f76ea0da702ac252937321c48eb249bc24d087521afdef`。

v3桌面、390px窄屏顶部和底部三张截图均已实际目视：四字段和只读信息清晰，
取消/确定可达，width=scrollWidth=356，height666/scrollHeight744，无横向溢出；
browser、console、HTTP errors均为空。证据写入于
`2026-11-13T00:47:45.765470+00:00`，只读身份复核于
`2026-11-13T00:50:09.473100+00:00`。

完整绑定为 `browser-frozen-v3/frozen-binding.json`；该阶段 `reconciliation.json` 指向v3，
并保留源码、v2分层历史。本次通过的是v3物理包的入口、交互及身份绑定，业务验收
仍保留唯一真实保存结果的 `native_source_review_pending` 失败和已签发下载。

## 最终 v4 统一冻结包最小续验

最终物理快照为
`/dev/shm/office-four-format-numbering-print-metadata-20261113-v4/source`，
manifest SHA 为
`f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be`。
v4 在 v3 基线上仅纳入 workbook-main 边距分类的一行修复及专项测试，PDF产品保持
相同。本专项使用该快照的 static、PDF engine 和 frontend，继续复用唯一源码链
实际下载的1499字节 PDF，未使用 live 工作树或引入并发PDF拆分改动。

`browser-frozen-v4.log` / `.exit-code` 为0；本版只执行一次最小续验，覆盖真实入口、
四字段baseline回读、取消、编辑历史、重排旋转及刷新恢复。savedRevisions=0、
HTTP save请求=0，没有重复完整保存、下载或完整测试。browser、console、HTTP
errors均为空。108次实际静态响应覆盖54个不同文件，逐次响应SHA匹配v4物理磁盘，
54个文件全部映射最终manifest；PDF主模块为 `assets/lazy-pdf-main-ER-OQgB0.js`。

本次授权最终HTML响应200、841字节，响应、`actual-native.html` 和物理
static/native.html SHA一致：
`b2693d7db9506a240ca768e33be181c81d579bbfce8bc18451bf6731fd77f9d6`。
10个产品/writer文件与v3物理快照、v4物理快照、v4登记和源码阶段原始身份逐一相等，
pdf-view-ribbon.ts也与v3及v4登记相等。210个已登记引擎文件逐一同v3，
dist/cli.mjs仍为 `2e7f096fc521e260e3f76ea0da702ac252937321c48eb249bc24d087521afdef`。
4个前端模块身份均从 `identityFrontend` 指明的v4物理frontend读取。

桌面、390px窄屏顶部与底部截图三张均重新实际目视，字段及只读信息可读、
取消/确定可达，无横向溢出；width=scrollWidth=356、height666/scrollHeight744。
证据写入于 `2026-11-13T00:53:20.691899+00:00`，只读身份复核于
`2026-11-13T00:53:51.446841+00:00`。最终绑定为
`browser-frozen-v4/frozen-binding.json`，`reconciliation.json` 当前仅指向v4，
`evidenceStages` 明确保留以下四层，不将历史结果替换为当前live验收：

| 证据阶段 | 身份绑定与有效范围 | 保存次数 |
| --- | --- | --- |
| 源码阶段 | source-identities.json；源码完整HTTP链、实际下载及独立pypdf回读，仅对应当时时点 | 1 |
| v2历史基线 | browser-frozen-v2/frozen-binding.json；仅v2物理包及其manifest | 0 |
| v3历史基线 | browser-frozen-v3/frozen-binding.json；仅v3物理包及其manifest | 0 |
| v4最终冻结包 | browser-frozen-v4/frozen-binding.json；仅本节最终v4物理包及其manifest | 0 |

最终入口与文件身份通过不改变业务验收状态：唯一真实保存结果仍为
`validation.ok=false`、`native_source_review_pending`，已核验文件身份的下载照常保留。
