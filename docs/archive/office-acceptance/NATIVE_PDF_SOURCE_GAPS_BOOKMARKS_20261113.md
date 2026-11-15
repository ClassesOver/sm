# PDF 非 AI 源工具核对与书签编辑专项

固定源：`/home/junge/pros/genoffice-source-full`，commit
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。以当前 worktree 为本地现状，不使用
早期索引判断现功能是否存在。源码位置以下均相对固定源 `apps/pdf/src`。

## 核对范围、已交付项与剩余边界

本表逐项核对 `renderer/App.tsx` 的 Home/Annotate/Edit/Fill Form/Form Design/
Page/View、目录/属性/图像浮动工具条、缩略图和字段上下文，以及其非 AI 宿主回调。
这是源业务入口清单，不以函数、翻译键、声明点或图标数量作为完成率分母。
Electron 操作系统菜单、打印机/证书存储等宿主能力单独标识，不假定浏览器自动具备。
AI 阅读、审阅和填表另有专项，不纳入此表。

本表当前状态于 2026-11-14 按 live 源码和后续专项记录校正，已实现但有边界的功能不再列为全缺。下文原始实施、失败与冻结验收记录继续保留；历史冻结资产不等于当前工作树整体验收。当前开放项另见 [有效缺口清单](NATIVE_PDF_ACTIVE_GAPS_20261114.md)。

| 源工具及源码位置 | 当前本地状态 | 剩余缺口／范围限制 |
| --- | --- | --- |
| 目录书签编辑：`renderer/App.tsx:7147–7316,9153–9211`；`OutlinePanel.tsx::PendingItem`；`main/save-pdf.ts:372,1684` | 已交付当前页新增、嵌套改名、删子树、清空、草稿历史及保存下载重开；实际树写回及页面身份映射见下文验收 | 含 URI／外部动作、坏目标、异常树及签名／保护来源仅阅读，不以局部树覆盖 |
| 无嵌入目录时从标题推导：`App.tsx:1691`；`heading-outline.ts::buildHeadingOutline` | 已接通：`pdf-heading-outline.ts` 优先嵌入目录；缺失或读取失败时调用固定源标题扫描器，最多扫描前 400 页，取消后不继续扫描；推导树只读导航，不写入 PDF 书签。真实 PDF.js fixture 覆盖嵌入目录优先、正文不误判、标题层级、页 0、读取失败回退及取消。 | 源生成目录本身不可直接编辑；此项不再列为本地缺口 |
| 属性前四字段编辑：`PropertiesDialog.tsx:37–129`；`App.tsx:4623` 的 metadata | 已交付 title／author／subject／keywords 编辑、清空、草稿历史、真实预览及保存下载；见[四项属性验收](NATIVE_PDF_METADATA_SOURCE_ACCEPTANCE_20261113.md) | 仅四字段；签名／加密保护／动态 XFA／能力不明来源只读，既有独占操作组合限制保留；不扩展为任意 Info／XMP 编辑 |
| 压缩文件：`App.tsx:6549,8955` → `pdfApi.reduceFileSize`；`main/pdf-shrink.ts` | 已接 Page 压缩命令与 api.shrinkPdf，生成独立压缩文件并返回大小和下载身份 | 仍受来源及预算限制；不等于桌面原路径替换或任意 PDF 都可缩小 |
| Bates 编号：`App.tsx:5315–5343,8988`；`BatesDialog.tsx`、`bates.ts` | 已交付源配置、可搜索逐页编号文字、页面身份快照及保存下载重开；见[Bates 验收](NATIVE_PDF_BATES_SOURCE_ACCEPTANCE_20261113.md) | 按应用时页面顺序固定编号；重排不重编号、删页不补号、后插页不自动编号。源无后缀及字体选择，不列为迁移缺口 |
| 拆分 PDF / 合并 PDF 文件：`App.tsx:9049–9061` → `openSplitDlg/mergePdf` | 已实现文件级拆分多产物与多来源合并，独立身份/下载链见 NATIVE_PDF_SPLIT_BATCH_SOURCE_ACCEPTANCE_20261113.md、NATIVE_PDF_MERGE_SOURCE_ACCEPTANCE_20261113.md | 来源/页数/输出预算及干净草稿限制保留；复杂表单字段树、导航与关联批注的任意来源等价未完成 |
| 比较文档：`App.tsx:4446–4466,8048–8070`；`ComparePanel.tsx` | 已接第二来源、只读文字差异与定位；实现见 pdf-compare.tsx、pdf-compare-compute.ts | 复杂来源与完整桌面交互/视觉等价尚未穷尽；文字比较不证明像素比较 |
| 证书签名、签名面板：`App.tsx:8461–8493,7960`；`CertSignDialog.tsx/SignaturesDialog.tsx` | 已有数字签名读取和基础完整性展示，见 pdf-digital-signatures.ts；证书签署仍未开放 | 缺实际证书签署、密钥托管/签名服务与证书信任链/吊销验证；普通签名图像不算数字签署 |
| 普通签名的图片模式与复用库：`SignatureDialog.tsx:158–181,245,288–335,417`；`main/signature-store.ts` | 已接手绘/键入/图片和复用库，见 pdf-signature-dialog.ts、pdf-signature-store.ts | 浏览器存储/来源限制与桌面宿主不同；普通签名库不提供证书签署 |
| 静态填表的文字/勾/叉/完成：`App.tsx:8614–8687,8004` | 已实现文字、勾叉、放置/编辑、同页移动/删除、保存后重编及必填软提示，见 NATIVE_PDF_STATIC_FILL_ACCEPTANCE_20261113.md | 静态内容为图像，不可搜索或交互；跨页移动和任意复杂来源不支持，metadata 失败可能不能再编辑 |
| 签名字段创建：`App.tsx:8747–8762` 的 signature | 已接空签名 Widget 创建与设计入口 | 创建签名字段不等于实际证书签署；复杂来源仍受能力限制 |
| 表单保留绘制工具、设计预览、自动检测：`App.tsx:8784–8824` → keepTool/preview/detectFields；检测实现在 `4316` | 已有设计预览、受限字段检测和 Ctrl 连续创建；见字段检测及多字段创建验收 | 检测仅支持已验证来源和候选类型；完整源检测/工具生命周期等价仍须逐项验证 |
| 字段复制/重复/粘贴：`App.tsx:11192–11215` 上下文回调 | 已支持待保存字段及安全已有单控件 text/checkbox/choice/date、空签名占位及安全 radio 整组（含跨页来源）的复制/重复/粘贴、快捷键、同文档跨页和唯一新名称；见 NATIVE_PDF_PENDING_FORM_CLIPBOARD_ACCEPTANCE_20261114.md、NATIVE_PDF_SOURCE_FORM_COPY_ACCEPTANCE_20261114.md | 已有复杂字段/实际或扩展签名/复杂 radio 结构；原 Widget 迁页的源支持待核实、系统及跨文档剪贴板未支持；不保证副本自动避让 |
| 图像浮动工具条剩余动作：`App.tsx:10952–11035` 的 rotateSelected/openImageDialog(cutout)/toggleImageLayer/deleteSelected | 已有移动/尺寸/替换/翻转/裁剪/透明度、顺逆 90° 旋转、去背景及安全页面直属图片逻辑删除与文字上下层级切换；见 pdf-existing-image.ts 和 NATIVE_PDF_EXISTING_IMAGE_DELETE_ACCEPTANCE_20261114.md | 含Form/无直属文字等复杂来源的层级切换受限；模板/静态填表记录来源的通用图片删除受限；旋转/镜像/模板对象等复杂来源有安全限制 |
| 完整打印设置：`App.tsx:11563–11736`；`print.ts` | 已有全部/当前/自定义页范围及奇偶筛选，见 pdf-print-dialog.ts；调用浏览器打印 | 打印机、份数、整理、双面等设备设置仍依赖宿主；不把浏览器系统框当成应用内已对齐 |
| 自动 OCR 与继续/取消：`App.tsx:2495–2571,11082–11103`；`ocr-layer.ts/ocr-bake.ts` | 用户已于 2026-11-11 明确排除 OCR，阅读继续使用现有文字层 | 不列入本次交付缺口；不将扫描页识别宣称为已实现 |
| 加密 PDF 打开及原保护修改/移除：`PasswordDialog.tsx`、`ProtectionDialog.tsx:125–135`；`App.tsx` 的 sourcePassword/protectionDirty | 当前受控保护入口仅从可读取已保存来源生成独立保护下载；PDF 打开无密码回调 | 输入来源密码后打开、保持原文件密钥以及修改/移除原保护的生命周期未接；本地“保护下载”仅关闭其独立子能力 |
| 缩略图右键与拖放这一入口形态：`App.tsx:9304–9448,11116–11169`；`PdfThumb.tsx` | 已有缩略图右键、旋转/删页/提取/插入/顺序命令及按稳定 pageId 拖放排序 | 全部未保存 overlay 的缩略图联动、复杂来源与大文档性能尚未穷尽；外部拖放依赖宿主 |

其余已见接线的非 AI 功能组：保存新修订/UndoRedo；原位改字及文字样式；文字
标注四型/移除；便签/回复/已有便签编辑删除；源绘图各型/测量标定/涂黑；手绘和
键入签名；受控密码保护独立下载；插图/链接/水印与页眉页脚；PDF 转 Word/XLSX/
PPTX/Markdown/HTML 与 PNG/JPEG 导出；已有表单值和字段导航；已支持类型的字段
创建/属性/排列；旋转/删页/提取/插入/替换/空白页/裁切/尺寸/反序/N 合 1/每页拆格；
缩略图/目录/批注/附件/搜索/双页/夜间/页码跳转/缩放/适宽适页。这是现有接线判断，
不新增“全部输入和文件均已验收”的结论。

桌面 File/窗口菜单的打开/新建/最近文件/多标签/另存路径由 Electron 宿主管理；本地对应
授权文件进入、新修订保存、派生下载和任务窗口。未声称两套宿主菜单语义已逐项等价，
也不将本轮目录专项扩大为操作系统宿主验收。

## 本轮书签设计和范围

复用固定源 `applySaveRequest({outline})`，不改固定源文件。完整书签树叶节点携带
不可变来源 pageId、top 和子树，转换时复用本地 blankIndex。新增空白页先追加，
书签按来源索引写入后再删页/重排，最终 `/Dest` 指向保留页面对象引用。删除父条目
同步删除子树；删除其目标页也裁掉此子树。全部裁掉时传明确空树，避免源写入器的
“输入非空但全部被删则不覆盖原树”回退留下悬空目标。显式清空也支持。

编辑动作逐次进入原 NativeDraft，无独立历史或存储；保留旋转、删页、重排、空白页、
批注等原生可组合操作，UndoRedo/恢复/保存请求均复用原链。原本独占的页面重新排版、
对象设计等仍按现有边界执行，没有为本专项新增“必须单独保存”的限制。

按源边界，含 URI/外部动作或无法完整解析目标的原目录仅可阅读，不允许用局部树
覆盖整个目录；阅读外链保持原功能。命名目标可解析时转为来源 pageId，不误列为全禁。
来源签名/保护/动态结构和异常循环/超深树拒绝相关写入能力，不影响已生成文件签发。

新模块：`frontend/src/pdf-outline-edit.ts/.css`、`pdf_engine/bridge/outline.ts`。
必要局部接线：`pdf-main.ts` 目录生命周期、`pdf-operations.ts` 校验/页投影、桥接
`operations.ts` 的模型/schema/正常 SavePdfRequest/结果复核及
`native_pdf_contract.py` 原回执种类集合。未新建路由或签发函数。

## 验证记录

证据与真实宿主验证持续记录于独立 `/tmp/office-pdf-outline-edit-20261113`，不改共享
static/dist。原目录外链 8d4–0015 验收保持独立，不当作本轮可写目录的证据。

### 定向契约与故障回归

- 新后端契约为 `pdf_engine/bridge/outline.test.ts` 7 项与
  `blank-note-composition.test.ts` 1 项；新增前端为 `pdf-outline-edit.test.ts` 5 项。
  初始书签模型/协议的 RED 为 5 失败 1 通过，前端初始 RED 为缺少新模块。
- `logs/pdf-outline-engine-related-20261113.log`：书签当时 6 项、空白页便签 1 项，
  连同 `blank-pages` 与 `local-note-replies` 共 14 项通过。随后只运行新增的写后复核
  故障用例，`logs/pdf-outline-advisory-20261113.log` 为 1 项通过，不把这两次描述成
  最终整套重跑或重复累计相同用例。
- `logs/pdf-outline-ui-final-20261113.log`：书签 5、阅读 Ribbon 4、页面操作 17，
  合计 26 项通过。临时锁后的行内改名有独立 RED（1 失败 4 通过），修复后包含在此
  定向 GREEN 中；锁期间保留未提交输入，解锁后仍可正常提交。
- 组合验证暴露的既有空白页便签问题有不带 `setOutline` 的独立 RED：
  `logs/pdf-blank-note-red-20261113.log` 是 `base.getPage(blankIndex)` 越界。
  `note-timestamps.ts` 仅在新空白页上将原 `/Annots` 前缀视为空，继续严格复核输出
  数量和身份；上述定向 GREEN 已覆盖原场景。
- `logs/pdf-outline-service-20261113.log`：新增真实源码桥服务测试 1 项通过。
  `test_outline_review_warning_retains_saved_download_and_failed_validation` 在真实保存后
  注入 `pdf_outline_output_review_failed`，确认修订登记成功、`validation.ok=false`、
  具体 issue 保留，下载字节可由 pypdf 读取真实书签和页文字，原来源字节不变。
  本轮未新增签发函数或可能失败的签发步骤，未改签发链，只向原回执追加复核告警。

### 真实 HTTP、保存、下载与独立回读

`browser-source-third/` 使用真实 NativeEditorService、授权 cookie/CSRF、工作区、
新修订保存与实际 TypeScript 源码桥；仅身份与仓储使用既有内存夹具。前端是 Vite
源码入口，不是冻结生产包。浏览器完成嵌套改名、删子树、当前页新增、UndoRedo、
反序、插空白页、空白页书签、删目标页、草稿刷新恢复、真实预览、rev4→5 保存、
授权下载及 rev5 重新打开导航。预览全部 applied、0 skipped、0 reviewIssues；
浏览器错误、console error 与 HTTP error 均为空，原来源 SHA 不变，savedRevisions=1。

完整脚本末尾曾因独立验证器把合法 pypdf `NullObject` 当数值而退出 1；保存下载与
重新打开已完成，原 `failure.json` 保留。只修正验证器对 null 顶部目标的读取，随后
对同一下载文件另起进程回读退出 0；不把完整脚本伪称退出 0，也未重跑整个生命周期。
`browser-source-third/independent-verification.json` 确认三页、原标题保留，书签依次为：

| 书签 | 最终 0-based 目标页 | top |
| --- | --- | --- |
| 修订书签 | 2 | 320 |
| Second renewed | 0 | null |
| Blank | 1 | null |

下载文件 SHA256 为
`92746ed12ee9b9856b05a1741866d7f8d8f399413a101923380b93b0ca2982ee`，
实际字节大小与签发身份相符。`evidence.json`、`http-evidence.json`、原/下载 PDF 和
重新打开截图保留在该目录。

### 最终源码最小续验与类型边界

完整流程后仅修正目录按钮为固定源式 `✎/✕/✓` 图标及临时锁的输入提交保护。
`browser-source-final-minimal/minimal-evidence.json` 对最终源码入口进行了最小真实
HTTP 续验：编辑入口、改名/删除/新增、UndoRedo、页组合及 1440×900/390×700
视觉截图。脚本退出 0，未再保存/下载（savedRevisions=0）。两张截图实际目视，
目录标题与动作均可读，侧栏 clientWidth=scrollWidth=149，无横向溢出。窄屏正文
仍采用原宿主横向阅读方式，不声称所有 Ribbon 组同时展开。

最小续验记录的 `pdf-main.ts`、`pdf-outline-edit.ts/.css`、`pdf-operations.ts` 和真实
PDF.js worker SHA 已逐一重新对磁盘比对相同；根 `reconciliation.json` 明确保留
完整脚本退出 1、验证器单独回读通过、最终最小脚本退出 0，以及未重复完整流程的事实。

最终前端 `tsc --noEmit` 于 `logs/pdf-outline-types-final-20261113.log` 退出 0。
独立引擎模块类型检查未通过：`logs/pdf-outline-engine-types-20261113.log` 只有固定源
`src/shared/ipc.ts` 的四个缺失类型包诊断（`@genoffice/ui`、`@genoffice/i18n`、
`@genoffice/ai-provider`、`@genoffice/electron-utils/print-job`），未通过伪造 shim
掩盖；不据此声称引擎严格类型检查通过。Python/MJS 语法及局部 diff 空白检查单独验证。

前两批失败证据也保留：`browser-source/` 的新入口 TDZ 已通过延后读 model 修复；
`browser-source-second/` 是源码 Vite worker 静态路径 404 与测试点击早于 preview
finally，分别只修烟测同版 worker 夹具和等待条件。它们不计为成功验收证据。

产品代码随后冻结，由主任务统一构建/LOCAL 身份更新。专项烟测现接受
`PDF_OUTLINE_EDIT_STATIC` 直接挂载冻结静态目录、`PDF_OUTLINE_EDIT_ENGINE` 选择
主任务提供的隔离桥；该模式不启动 Vite、不重写 HTML、不复制旧资源，并逐一记录
浏览器实际静态响应与磁盘文件 SHA。不以源码验证代替最终资产验收。

### 87a 冻结包最小验收

证据：`/tmp/office-pdf-source-gaps-20261113/browser-built-entry-final/`。
采用主任务统一冻结静态目录
`/tmp/office-four-format-source-entry-20261113/static` 与隔离桥
`/tmp/office-four-format-source-entry-20261113/engines/pdf_engine`，端口 4408。
冻结 manifest SHA256 为
`87a8aff45cc2cb8593f2525615895f505fb6721950ff27f5a56de5d034f9efbb`。
使用 `/dev/shm/office-source-entry-browser-tmp` 及 CDP `Network.setCacheDisabled=true`，
不修改旧证据、不启动 Vite、不重写 HTML、不复制旧静态资源。

`runner.log` 退出 0；`minimal-evidence.json` 确认真实 HTTP 授权入口、打开编辑不脏、
改名/删子树/当前页新增、UndoRedo、空白页/删页/重排组合。无保存下载重跑，
savedRevisions=0。浏览器、控制台与 HTTP 错误均为空。桌面 1440×900 和窄屏
390×700 截图均实际目视，目录书签及动作可读，clientWidth=scrollWidth=149。

51 次静态响应对应 50 个唯一资源，其响应字节 SHA 逐项匹配当前冻结目录中的文件，
包含实际 `lazy-pdf-main-DGKGqgvR.js`、`pdf-main-euDrcvw7.css` 和
`pdf.worker.min-CLrFZWeq.mjs`。`frozen-reconciliation.json` 还核对四个书签相关源码
SHA 与主任务 `source-before-build.json`、当前磁盘及烟测记录均相同，并记录冻结
manifest 的 PDF 入口/样式/worker 绑定。该层仅关闭最终冻结包入口与资源连续性，
完整保存/下载语义仍由前述源码真实生命周期及独立下载回读支撑，不声称完整流程
在最终冻结包重复执行。

### 最终 68ce 构建的资源连续性

主任务随后只调整 Word 图库内容/窄屏样式并重新构建，PDF 产品及隔离桥没有变化。
最终 manifest SHA256 为
`68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`。
按主任务要求，没有重复 HTTP 完整链或保存下载；使用保留的
`/dev/shm/office-source-entry-87a8-static` 逐项核对上述浏览器实际加载资源，并与
最终静态目录 `/tmp/office-four-format-source-entry-20261113/static` 对比。

证据目录：`/tmp/office-pdf-source-gaps-20261113/final-68ce-continuity/`，含
`resource-continuity.json` 和 `verify-resource-continuity.py`。先确认旧快照 manifest
确为 87a、最终 manifest 确为 68ce，且每个旧资源 SHA 都与 87a 实际 HTTP 回执一致。
50 个唯一资源中 45 个原始字节完全相同；另 5 个为以下生成文件引用变化：

| 逻辑资源 | 87a 文件 | 68ce 文件 | 内容判断 |
| --- | --- | --- | --- |
| native-main | `lazy-native-main-BbIRL0Pq.js` | `lazy-native-main--GRcyT1M.js` | 仅资产引用 |
| pdf-main | `lazy-pdf-main-DGKGqgvR.js` | `lazy-pdf-main-CEjvUO51.js` | 仅资产引用 |
| unified-main | `lazy-unified-main-CIau0rZP.js` | `lazy-unified-main-B3CjOlKm.js` | 仅资产引用 |
| PDF 图像导出 | `lazy-pdf-image-export-B2diZB4F.js` | `lazy-pdf-image-export-BmY7zZMw.js` | 仅资产引用 |
| PDF 文字导出 | `lazy-pdf-export-text-tYaHdpcn.js` | `lazy-pdf-export-text-D5IqwECy.js` | 仅资产引用 |

“仅资产引用”的判定不是忽略全部 hash 文本：按两代 manifest 精确匹配旧键；改名项
只在未匹配候选唯一时配对，避免 `index` 等重名混淆；每个 manifest 资产使用独立
token，仅替换实际登记的完整生成路径/文件名。上述 5 个文件归一后全文 SHA 相同，
JSON 同时保存原始 SHA、最终 SHA、归一 SHA 和确切引用替换列表。其余文字、
变量、条件、数字、样式及执行语句都不被归一。`native.html` 同样仅入口资产引用变化。

另外由 50 个已加载资源递归补齐 manifest 的静态 `imports/css/assets` 闭包，共 51 项。
唯一新增核对项 `cursor-editorTextHighlight-kG3uUOwL.svg` 两代原始字节相同；闭包的
静态依赖图无变化。目录样式、PDF.js worker 及其它已加载依赖均在 45 个相同字节项中。
未发现这一已验证 PDF 范围内的真实代码或样式变化，因此没有新增 UI 补验触发项。

未触发的 Word、工作簿、幻灯片动态入口不因资源名出现在 preload 表中就计为浏览器
已加载，也不把它们的逻辑宣称为不变。最终 PDF 验收依据为：源码完整生命周期与
独立回读、87a 真实最小浏览器验收，以及该 68ce 精确资源/静态依赖闭包连续性。
