# PDF Bates 编号固定源接线与验收

固定源 `/home/junge/pros/genoffice-source-full`，commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮重新核对源 App、BatesDialog 和
bates.ts，以及当前 worktree 的页面操作、图章和文字插入实现；不使用旧索引代替现状。

## 源入口与字段

- `apps/pdf/src/renderer/App.tsx::applyBates`（5310 起）：取应用时 `visList` 的显示顺序，
  逐页构造几何、调用 `buildBatesInserts`，再映回不可变原页面索引；一次 `applyEditOps`
  进入原历史。插入空白页参与当时的编号，已删除页不参与。
- App 的 Page ribbon `setBatesDlg(true)`（8988 附近）及 `BatesDialog`（11329 附近）。
- `apps/pdf/src/renderer/BatesDialog.tsx` 与 `bates.ts`：前缀、非负整数起始编号、
  1–15 位补零、6–36 号字、黑/红/蓝/绿四色、左/中/右×上/下六位置、1-based
  起止页（末页留空到末页）、编号样例。源没有后缀、字体选择、粗体或斜体，不扩充。
- `buildBatesInserts` 返回原生 `TextInsertInput`，不是页码位图：可搜索文字，数字超出
  位数不截断；计数从所选范围第一张开始；28pt 显示边距，经源 `viewToPdf` 处理
  CropBox、旋转和 UserUnit；居中/右对齐通过测量后的 `lineXOffsets` 传给源写入器。
- 应用后是固定内容：后续重排不重编号，后插入页不自动编号，删目标页不补号。空范围
  在源 App 中关闭而不产生编辑；本地也保持不脏。

原本地 `setStamps` 是全页覆盖的 PNG 水印/页眉页脚，且设置后锁定页结构；普通
`insertText` 又是单操作独占路径，二者都不能原样表达上述源语义。因此采用小型
`addBates`，复用原正常 `SavePdfRequest.textInserts` 与 preview/save/签发链，未将
普通页码或图章近似当作 Bates，也未扩大普通文字插入的现有边界。

## 接线、身份与操作语义

`addBates` 携带必需 `sourceSha256`、完整源配置，以及按应用顺序排列的 entries：
`{pageId, ordinal, origin, rotate, lineXOffsets}`。每项绑定原来源页或已登记 blank 页；
后端按配置与应用序号生成编号文字，而不是接受另一份任意正文。序号、页面身份、
重复目标、配置字段和坐标在生成前校验。删除原页时后端不为它写编号；撤回未保存
blank 时前端移除它的 entry，但保留其它 entry 的 ordinal，因此号码可以有空号。

源几何、编号生成与验证被保留到 `pdf_engine/vendor/bates/`，两端共用：

| 文件 | 来源/适配 |
| --- | --- |
| `bates.ts` | 固定源 bates.ts 完整逻辑，仅调整 type/geometry import 并补归属注释 |
| `geometry.ts` | 固定源 annotations.ts 的 PageGeom、geomDispSize、viewToPdf 原样摘录 |
| `types.ts` | 固定源 IPC TextInsertInput 原样摘录 |
| `protocol.ts` | 本地原生身份/草稿契约，不属于固定源逻辑 |

来源原始/本地 SHA 记录在 `/dev/shm/office-pdf-bates-20261113/source-provenance-for-root.json`。
共享 SOURCE/LOCAL 登记由主任务统一处理，本专项未修改。

前端入口为 Page ribbon 的 `genoffice.pdf.page.bates`，独立配置模块
`frontend/src/pdf-bates.ts/.css`。打开/取消不脏，应用作为一项 NativeDraft action，
支持 UndoRedo、同修订恢复、锁/只读检查及过期配置拒绝。草稿文字预览按应用时的
PDF 文字矩阵显示，保存仍须核对真实 PDF 预览并确认。页面结构和来源身份复用原
`pdfPageState`，没有另建存储或工作区。裁切、后旋转不会改写应用时 origin/rotate。

本地边界：沿用原生操作总数/JSON 大小限制，每项 Bates 最多 2000 个编号页、前缀
最多 200 字符且不允许控制符、起始及分配号码须为安全整数；签名、加密保护、动态
XFA 来源不可添加 Bates。源配置未开放的样式字段不接受。既有独占对象设计、页面
重新排版等仍按原功能边界处理，不为 Bates 新增“必须单独保存”的限制。

后端 `bridge/bates.ts` 校验配置/目标并生成原 `textInserts`，正常桥写入后再用独立
PDF 文字读取确认编号、字号及最终裁切风险。写入器跳过信息进入原回执，生成后的
提取/版式复核只形成 `reviewIssues`。`native_pdf_contract.py` 的原 confirmation
集合增加 `addBates`，由已有 receipt 集合派生纳入；未新增路由、签发函数或签发阶段，
没有新增可阻断下载的验收门禁。身份错误仅拒绝使用对应请求；真实生成后的告警
不丢弃实际文件。

## TDD 与定向验证

所有本轮证据及浏览器临时文件位于 `/dev/shm/office-pdf-bates-20261113`；未复制
node_modules、未覆盖共享 static/dist、未运行完整 suite、未提交或部署。

- `engine-red.log`：新增真实写入与组合测试在缺少 `addBates` schema 时失败（2 失败、
  非法请求拒绝项 1 通过）。两个命令路径准备错误另存 `*-setup-error.log`，不算 RED。
- `ui-red.log`：新增 Bates 模块不存在；`ribbon-red.log`：源 Bates 入口缺失的行为断言
  失败。不是将普通水印入口当作已有 Bates。
- `engine-related.log`：Bates 当时 4 项、既有 blank-note 1 项、书签 7 项，共 12 项通过。
  `engine-supplement.log`：只补既有/新增便签组合和保护来源能力 2 项，均通过。
  本轮新增引擎合计 6 个不同契约：可提取正文、组合映射、无效输入、软复核故障、
  便签保留、保护来源拒绝。不把早期重复定向试跑累计成额外覆盖。
- `ui-related.log`：Bates 当时 4 项、Page ribbon 1、stamps 2、页面操作 17，共 24 项通过。
  对源空范围再写 `empty-range-red.log`（1 失败），随后仅跑空范围和六位置/UserUnit
  两项，`ui-supplement.log` 为 2 通过。最终新增前端契约共 6 项。
- `service.log`：新增真实源码桥服务契约 1 项通过（26.24s）。在普通 text feature
  关闭时 Bates 仍按 PDF 原生功能预览；未确认保存被原预览确认契约拒绝。确认后
  注入 `pdf_bates_output_review_failed`，修订仍登记、validation=false、真实下载可读
  到 `CASE-0009` 和原正文，原来源字节不变。
- `types-first.log`：前端 tsc --noEmit 退出 0，发生于最后仅空范围 no-op 补丁前；
  最终完整类型与冻结构建由主任务统一检查，不把该日志冒充最终冻结资产身份。
- Python/MJS 语法和限定文件 diff --check 已检查。源六位置、CropBox 与 UserUnit
  有定向行为断言；完整真实保存另覆盖已旋转裁切页。

## 真实 HTTP 保存与独立下载回读

`browser-source-second/` 为真实 NativeEditorService/授权 cookie/CSRF/工作区/保存新
修订与实际 TypeScript 源码桥，只有身份与仓储复用现有内存夹具。前端 Vite 源码，
不当作冻结生产包。最初 `browser-source/` 仅因 Vite 端口 4413 已占用而启动失败，
尚无业务请求；换到宿主 4424/Vite 4425 后完整脚本退出 0，未修改产品来绕过失败。

完整路径：反序→插空白页→打开不脏→配置 `CASE-`、41、6 位、12 号、蓝色、
上方居中、范围 2–4→应用→UndoRedo→删除已编号原页→再反序→插入新空白页→
后旋转原页→刷新恢复→实际 preview→确认→rev4→5 保存→授权 PDF 下载→rev5
重新打开。所有操作 applied，0 skipped、0 reviewIssues；浏览器/console/HTTP errors
均为空，source SHA 不变，savedRevisions=1。

独立 Python 进程使用 pypdf 回读同一下载文件，不依赖写入器或其 inspector，确认：

| 最终 0-based 页 | 实际正文 | 含义 |
| --- | --- | --- |
| 0 | `CASE-000043` | 应用时的空白页，重排后仍保留43 |
| 1 | `Original page 2`、`CASE-000041` | 裁切/原90°页，后再旋转至180°，仍保留41 |
| 2 | `Original page 3` | 申请范围外，无编号 |
| 3 | 空白 | 应用后插入，无编号 |

被删原页的 `CASE-000042` 和原正文不存在；原标题 `Preserved Bates source` 保留。
独立 visitor 回读实际字号12、颜色蓝、原生文字矩阵与应用时 literal CropBox/旋转
origin（空白页 `[150,360]`；裁切旋转页 `[50,200]`）及对齐偏移相符；没有图像
XObject，证明是实际可搜索编号文字。文件 SHA 与签发身份、size 一致：

`7becda57c6f95580886c8c87f3d86f75cc5bea4d49032f7b856f080cea3c293d`，7635 bytes。

`evidence.json`、`http-evidence.json`、`downloaded.pdf`、
`independent-verification.json` 及截图均保留。保存结果的 validation 仍是
`native_source_review_pending` 失败，下载照常签发；不标记业务验收通过。

## 最终源码最小续验（冻结前阶段）

完整流程后仅补源空范围的 no-op，未重跑保存下载。
`browser-source-final-minimal/` 最小脚本退出 0，确认该分支不脏、最终编辑入口/字段、
UndoRedo、结构组合和草稿恢复；保存次数为0。桌面 1440×900、390×700 对话框顶部
与滚动到底截图均实际目视，颜色/位置/预览/取消/应用可达，dialog clientWidth=
scrollWidth=356，纵向滚动高度1027，属于可滚配置表单而非被遮挡的按钮。

最终五个前端模块 SHA 与磁盘重新核对一致，记在最小 evidence；根
`reconciliation.json` 明确完整脚本退出0、最终最小退出0、空范围补丁后未重复完整
链及当时尚非冻结包。产品已通知主任务冻结；该阶段待统一物理源码快照、构建和静态身份
给出后，仅补冻结入口/资源 SHA 与必要视觉，不重复 HTTP 保存链。


## 最终统一冻结包最小续验

主任务从物理快照 `/dev/shm/office-four-format-source-library-20261113/source`
统一构建，静态目录为同根 `static`。本专项在收到构建完成与 manifest 身份后，
只执行 `PDF_BATES_MINIMAL=1`，没有启动 Vite、重写入口或复制旧静态资源，也没有
重跑完整 preview/save/download 链。最终 manifest SHA：

`845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c`。

证据位于 `/dev/shm/office-pdf-bates-20261113/browser-built-final/`，命令日志为
其同级 `browser-built-final.log`，脚本退出 0。冻结入口实际加载
`assets/lazy-pdf-main-DgaOa3R9.js`，Bates 入口及完整配置、空范围 no-op、应用后文字
预览、UndoRedo、后续结构组合和刷新草稿恢复均通过。保存次数断言为 0；独立核对
HTTP 请求记录，`POST .../api/save` 为 0。

捕获 106 次同源静态资源 200 响应，共 52 个不同文件；每次响应字节 SHA 与最终
静态目录文件一致，52 文件全部映射到该 manifest 的 file/css/assets。五个前端
模块、四个 Bates vendor 模块、两个引擎 bridge 模块和 native confirmation 契约，
共 12 个文件的当前 SHA、物理快照 SHA 与 source-identities 登记逐一一致。
最终 PDF 引擎 `dist/cli.mjs` SHA 与 build-identities 登记一致：

`0ce17adca76684aa8875786f77981a9c1f833a80069de64fe0394e71cbeea8c8`。

桌面、390px 窄屏顶部与滚动到底截图重新实际目视：配置字段、蓝色/上方居中、
样例、取消和应用按钮清晰可达；无横向溢出，dialog width/scrollWidth 均为356，
height666/scrollHeight1027。浏览器、console、HTTP errors 均为空。
完整身份绑定保存为 `frozen-binding.json`，不以先前 Vite 证据冒充最终冻结层。
本轮只追加验收记录与证据，未修改产品或共享构建资产；业务事实/完整版式验收
仍沿用前述失败告警，不因入口最小续验通过而改称业务验收通过。
