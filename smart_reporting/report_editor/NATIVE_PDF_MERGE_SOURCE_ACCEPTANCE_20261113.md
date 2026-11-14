# PDF 多文件合并：固定源能力与专项验收（2026-11-13）

## 范围与固定源

本项是“合并 PDF 文件”：当前来源在前，按用户所列顺序追加多份外部 PDF，生成独立
派生文档。不是 `mergePages` 的多页拼一页，也不是已有单文件插页/替换。
固定源为 `/home/junge/pros/genoffice-source-full`，HEAD
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

源 `apps/pdf/src/renderer/App.tsx:6616` 的 `mergePdf` 先 `flushThen` 保存修改，
再调用原生合并；`main/pdf-main.ts:1891` 核对基文档路径授权，打开多选文件选择器，
通过 `readMergeInputs` 按选择顺序读取，调用 `mergePdfBytes`，生成唯一新文件并打开。
同文件1181行合并输入总量上限为1 GiB，不去重输入。
`main/save-pdf.ts:1395` 的writer完整加载基文档，再按输入顺序copy外部所有页面。
本地对应函数与固定源逐字节相等，函数SHA为
`f712ef5e183b489aac8361fa4a18abaaf574762ce1a6021a1b5cb9ebb722bc3f`。

核对时live `page.mergePdf` 为禁用项且没有merge-pdf API；已有external-pages仅支持
单上传insert/replace，并保存当前文档新修订，不等于独立多文件合并。

## 产品实现与服务适配

新增合并对话框多选文件、显示与调整顺序、移除文件，取消不保存。确认提交后沿
`flushForFileOperation` 的原草稿/实际预览确认/保存流程取得真正保存回执，授权新
修订并读取新context/CSRF；核对文档、修订、scope和来源SHA后再发送合并。
同SHA新修订仍重新授权。来源未登记或授权失败时不合并，原已保存下载保留。
入口小宿主同步绑定；合并流程与对话框在首次点击时才动态载入。

服务端沿原session scope、Origin、CSRF与来源SHA校验；外部文件逐份校验严格base64、
PDF头和SHA。上传只来自有界字节，不接受客户端任意路径。固定源writer负责实际
合并，不另造PDF writer；输出后置页数/页面几何复核仅软告警。

`native_pdf_extract.py` 只将原提取的派生发布尾部提取为内部共用helper；默认文件路径、
提示、来源pages回执、登记、身份独立回读及非阻断签发契约保持。合并传入自己的
身份键、文件名与提示，派生来源绑定父文档/修订/SHA，顺序外部SHA也进入身份键。
新增merge/helper已登记 `_SIGNING_CHAIN`，新增HTTP故障登记位于
`test_pdf_merge_http_preserves_verified_downloads_on_lineage_faults`。

与桌面源的差异必须保留：

- 桌面源合计1 GiB；Web复用现有外部页面上传总6 MiB边界，基来源与在线编辑仍沿
  现有24 MiB限制。派生输出超在线上限时保留实际下载，不开放在线编辑。
- 桌面源在操作系统选择器之前flush；Web在对话框确认前取消不会保存。
- 桌面源自动打开唯一新文件；Web显示实际独立文档下载/打开入口，下载名为merged.pdf。
- 不增加任意“最多10个文件”上限，不用源没有的复杂结构拒绝来替代合并能力。

固定源实际结构探针确认：基文档表单字段及Outlines目录对象保留，外部widget和Text
批注页图仍被复制，重复外部文件也按序追加；外部AcroForm字段树不被导入，输出表单
字段仍只有基文档字段。界面和回执明确提示外部表单字段树、目录及附件不保证完整
迁移，签名有效性不保证；不会声称任意复杂PDF无损合并。加密文件沿源PDF加载限制。

## 已执行定向回归

证据根：`/dev/shm/office-next-pdf-merge-20261113`。没有完整suite重跑，没有构建共享
static/dist；后端本阶段通过证据目录engine-source指向源码tsx执行真实引擎。

| 证据 | 实际结果 |
| --- | --- |
| backend-red.log | merge路由404，9个实际行为失败，退出1 |
| ribbon-red.log | 原merge禁用，与启用能力预期不符，退出1 |
| backend-green.log | 新merge与原extract/split共24 passed，真实下载、pypdf、顺序、重试身份、来源不变及授权输入边界 |
| frontend-complete.log | 对话框4项、保存后授权4项、Ribbon及初始模型读取各1项，共10 passed |
| fixed-source-structure-probe.log | 固定源真实复杂结构探针1 passed |
| bridge-green.log | 上述结构及实际writer后置复核故障共2 passed，复核失败保留字节 |
| nonblocking-green.log | 名称沿准备阶段保留，实际退出1：13 passed，2个测试误将既有安全拒绝403写为422；真实缺失/替换文件被正确拒绝，没有实际身份可用下载 |
| metadata-red.log | 错误类型/超长reviewIssues可使已生成文件返回500，2个真实RED |
| nonblocking-affected-final.log | 修复只丢不可信回执元数据；加上修正安全状态码断言共5 passed；含一条受影响receipt_identity重核验 |

上述非阻断记录合计覆盖17个不同用例：原split7类、新merge9类及签发静态守卫。
merge覆盖登记失败、回执伪造、写后回执异常、复核回执类型损坏、复核提示超长、
工作区写后回执异常、独立回读异常、实际身份被替换、实际文件缺失。
可核验实际文件始终可下载；实际文件缺失或身份被替换时只拒绝对应派生产物。
验收始终保持false/待复核，不将告警改成业务通过。仅有既有imghdr弃用告警。

## 最终冻结HTTP状态

`pdf-merge-smoke.mjs` 与 `pdf-merge-server.py` 已准备，语法与py_compile通过。
要求显式 `PDF_MERGE_STATIC`、`PDF_MERGE_ENGINE`、`PDF_MERGE_MANIFEST`、
`PDF_MERGE_SNAPSHOT`；启动前保存runner/server/继承server字节副本与SHA，浏览器
执行前保存源PDF与两份上传夹具的SHA，前后逐文件核对9条PDF链路Python的live、
物理backend-baseline和登记SHA，不宣称Python隔离或全基线运行身份。

拟执行：取消0save→改标题并反序→选择A/B并调整为B/A→未确认时0save/0merge→
核对实际预览并勾选→唯一一次保存到修订5→从新授权来源合并→实际下载→独立pypdf
检查基来源3/2/1及B1/A1/A2共6页、标题、原来源不变→派生文档重开6页。
并核对HTML、每个资源响应与物理manifest、首次点击动态加载和桌面/窄屏截图。
当前尚待root统一冻结manifest后运行，该准备记录不构成浏览器验收通过。

### 首次冻结 HTTP：0次保存的构建入口失败

root统一8项检查退出0后，首次使用manifest
`615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`
执行 `browser-frozen-01`，退出1。实际 **0次save、0次merge**，记录保留，不覆盖。
`pending-source` 填写标题超时，目视截图中的metadata输入禁用；状态栏完整错误是
冻结 `pdf_engine/dist/cli.mjs` 的 `Identifier 'createRequire' has already been declared`。
文件首行旧构建banner导入createRequire，22600行源wasm-path又导入同名标识，造成
Node解析失败，原位改字与metadata能力未能载入。不是通过删掉复杂来源支持避开失败。

实际执行live runner/server的字节与冻结源逐一相同；物理source无.venv，故工具使用
live Python host。三个脚本有启动前执行副本、SHA及结束后SHA，全部与冻结相同。
9关键后端文件的真实before/after-failure均相同且匹配baseline登记；不据此声称全部
后端或已漂移的其他模块也相同。见该目录 `failure-counters.json`、
`executed-harness-identities{,-after}.json` 与 `backend-{before,after-failure}.json`。
等待root更正冻结构建banner并重新核验后，因该轮没有保存，可在新目录继续完整链。

### 最终冻结完整 HTTP：唯一保存通过

root按现有package构建脚本的createBridgeRequire别名修复builder；旧PDF桥、metadata和
pre-http身份保留于统一根 `pdf-initial-banner-conflict`。源与前端manifest没有变更，
仅PDF桥SHA变为 `71031a5b456471902a0a5889f6527dd6e415ac77ce4d69f0462a2694804a304e`，
7个dist mjs逐一Node语法检查通过。

同manifest `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`
的 `browser-frozen-02` 完整链退出0：取消及未确认预览阶段均0次保存/合并；确认后
唯一一次save由修订4到5，新grant/context/CSRF从修订5执行唯一一次merge-pdf。
用户列表调整为B/A，实际浏览器下载的合并PDF SHA/大小与回执相符；独立pypdf回读
`Merge source page 3 / 2 / 1 / External B1 / External A1 / External A2` 共6页，
保存基文档及合并文档标题均为 `Merge saved title`，原来源SHA不变。派生文档实际
重开6页。原0save失败目录保留，没有重复完整保存。

HTML字节与物理native.html相等；128条浏览器资源验证记录对应64个唯一JS/CSS资源，
逐响应SHA和manifest映射均通过，不能将128宣称为唯一资源。原始服务器请求/缓存
响应另在 `network-counts.json` 计数。首次打开前无merge动态控件请求，首次点击后
实际加载。pageerror、console error与HTTP error均为空。

9条PDF后端文件在真正启动前与完成后的逐文件SHA均等于physical backend-baseline
及登记值，前后稳定；执行runner/server/继承server有启动前字节副本及SHA，结束后
字节仍与冻结源相同；源与两个外部PDF夹具在浏览器执行前登记SHA。PDF桥也有
before/after SHA，保持71031a5b不变。不以这9条记录泛化整个后端全部稳定，也不
宣称Python隔离；其他会话live漂移不被覆盖或刷新进旧基线。

三张结果截图均实际目视：桌面及390px窄屏下顺序按钮、告警、实际下载/打开、底部
操作可见；窄屏对话框宽356、scrollWidth356，无横向溢出，内容全部可放入当前高度，
因此窄屏首尾截图相同。具体证据为该目录 `evidence.json`、
`independent-verification.json`、`visual-review.json`、`backend-{before,after}.json`、
`executed-harness-identities{,-after}.json` 与 `engine-identity-{before,after}.json`。

本项固定源多输入文件合并功能完成来源/交互/实际产物验收；保存与派生validation
仍为false/待业务和完整布局复核，不宣称业务验收通过，不扩大到其他PDF工具族。
