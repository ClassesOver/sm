# 四格式对照续批记录：审阅、缩略图、图表和打印

2026-11-13。目标仍为四格式完整对齐 GenOffice，不将这些子能力当作完整验收，也不给未经穷尽核对的完成百分比。固定源 ref 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，应用分支 code。保留所有既有、未提交和并发改动，不提交／推送／部署。

## 已落地的本轮增量

| 格式 | 当前改动 | 已有验证及限制 |
| --- | --- | --- |
| Word | 审阅批注开关、按文档顺序前后导航；受支持正文修订导航；字数统计；复用固定源偏好键的浏览器拼写检查开关。 | 拼写默认开启、只影响对应 editor、只读仍可切换、销毁解绑；不是词典或独立语言校对服务。此前专项通过记录与本轮 `office-review-integration-20261113.json` 保留，不外推完整审阅。 |
| XLSX | 第一外层多级类别标签；line/area/radar 显式数值标签；line/area 横向类别轴；可见折线／面积内选择系列；null 分段、非有限值不产生幽灵命中；类别数量按 primary 系列，固定源不支持的 line/area reversed 不翻数据或文字。 | 子 agent 最终 chart-render 110/110；reader 类别／标签 21/21 及当轮引擎类型通过。系列按各自长度铺满是固定源约定，不静默改为另一数据模型。完整图表族和复杂格式仍开放。 |
| PDF | 独立压缩副本、打印范围／单双页、已有图片90/270度旋转；待保存静态填写、四类标记、水印／页眉页脚、绘图的缩略图投影；Page 压缩命令源顺序。 | 缩略图按来源／页面身份及 CropBox／rotation 映射，预览文件不叠加重复层；复用现有 SVG painter。helper/host 5 项及 painter/host 70 项通过（agent 工具输出，未留独立日志）；压缩 Python 3 项此前通过。Page 顺序 1 项 RED→GREEN。 |
| PPTX | 当前草稿打印入口、范围／隐藏页、五布局、预览、系统打印；补两个已有功能入口遗漏的源 SVG 图标；续补 Ctrl/Cmd+P 和图片加载清理。 | 首批46/46 定向，后续13/13及焦点1/1；两次冻结真实浏览器／PNG／独立PDF回读见[打印专项](NATIVE_PPTX_PRINT_ACCEPTANCE_20261113.md)。首批类型／预算失败，后续已收敛，详见下方续记。 |

root 重现 PDF 宿主 9 个失败后核对当前真实结构：水印与签名改为来源 Portal 弹窗，文档属性为 native dialog，目录增加独立编辑按钮。更新这些过时选择器但保留输入、取消、焦点、实际图片尺寸和文件大小断言；另外修复文档属性关闭时焦点返回隐藏按钮的真实问题（回退本宿主当前功能区 tab）。

组合专项 `office-review-integration-20261113.json` 为 **111/111**：PDF host 58、metadata 3、Word ribbon 45、spellcheck 2、category axis 3。证据归档在 `/home/junge/codex-evidence/smart_reporting/office-parity-review-print-20261113/`。它冻结了当时受测状态；后续 Word 新修订录制和其它并发变更另验，不冒充这些111项覆盖。

## 盘点与下一步

- [PDF Page 17 命令与全部缩略图 overlay 家族](NATIVE_PDF_SOURCE_INVENTORY_20261113_INCREMENT.md) 已逐源入口／本地回调核对，清楚区分已实现、受限、缺失和仅测试入口。它不是全 PDF 穷尽表。OCR 沿用用户已明确排除。
- PDF 续补textInserts后继续补了受限pending replaceText，精确验收见末尾；旋转/复杂样式文字、imageEdits、擦除live raster仍有差异。当前只有raster懒加载，pending DOM全页构建与源可见行策略也有性能差异。不能用“实际预览可见”关闭这些即时预览差异。
- Word 新跟踪修订录制／服务端可信作者日期／保存回读，以及 `w:trackRevisions` 设置由并行任务闭环。记录 operation 不接收客户端作者／日期；隔离冻结浏览器已完成开启／保存／下载／重开及关闭／保存／下载／重开；root 独立 ZIP 回读两份下载身份及设置值，详见[设置验收](NATIVE_WORD_TRACK_REVISIONS_ACCEPTANCE_20261113.md)。这不扩大到复杂正文修订。
- XLSX 完整透视／高级图表／打印／连接功能、PPTX 其余文件／审阅／媒体能力、四格式全部 AI tools 与恢复生命周期以及生产链等仍按原总范围推进。源自己未实现的能力单列源边界。
- 完整目标保持 active。本批没有完成审计证明全部要求已满足，不能标记 complete。

## 收敛续记

2026-11-13 再次 `git fetch origin code` 后，`HEAD...origin/code` 左右提交数为 `0 0`，两者均为 `1138887df2541b748ebe5746871e4198bb48a712`。保留工作区已有改动。

- Word 录制正文修订已具备真实 ZIP 保存／再次 inspect 的回归：服务端绑定作者、UTC 日期、不同插入／删除 ID、原段属性保留以及禁止客户端伪造作者。host 首次完整定向为 26 passed / 2 failed；两项非法 namespace 用例调整为同时验证 inspect 拒绝及旧锚 patch 拒绝后，仅复跑该参数组 3/3 通过，未重跑整套。当前会话 recorder 与文档 `w:trackRevisions` 设置仍需分开验收。
- XLSX 两个 threaded-comments fixture 已使用完整 typed `WorkbookModel` 工厂，包含真实 worksheet、styles、themePalette 必填字段；定向 3/3 通过，`/tmp/xlsx-thread-fixture-20261113.log` 保留当时 TypeScript exit 0。root 后续再次 `pnpm exec tsc --noEmit --pretty false` exit 0，日志 `/tmp/office-tsc-convergence-20261113.log`。这不追溯改变旧冻结构建的检查记录，也不等于资源预算通过。
- PPTX 补查打印 raster 取消清理：加载成功／取消／同批一张失败均解除图片回调和 abort 监听；未完成图片移除 src，失败后取消其余加载。新增三个用例先 3 项 RED，再 3/3 GREEN。文件菜单固定源的 `CmdOrCtrl+P` 快捷键接入同一当前草稿打印入口，组合键／模态框／其它编辑器焦点保持隔离；输入先提交再冻结快照。相关定向结果和后续真实浏览器范围另见打印专项续记。
- 新 `static-lifecycle` 冻结构建的现有预算检查 **0 失败**，未改预算脚本或限额；共享 Vite 新分包配置只按实际冻结结果记录，不冒称 root 独立完成或已验收全部格式运行路径。PPTX 新浏览器记录覆盖五布局、两个打印快捷键、183 份应用资源身份匹配、无保存／无新修订／无草稿变化。PDF 中文抽取兼容部首的问题仍存在。
- [PPTX 文件菜单八个源入口](NATIVE_PPTX_FILE_SOURCE_INVENTORY_20261113.md) 已补盘点，分别追到真实回调。原地保存与新修订生命周期差异、打开／另存为／AI 命名、矢量 PDF／PNG／JPG 导出等保持显式未对齐，不将临时打印 PNG 当作正式图片导出。
- PDF 插入文字缩略图续补：来源／页面身份校验后按当前 CropBox／rotation 映射首行基线、字体／颜色／对齐／行距，真正 PDF 预览后移除叠层，避免重复。root 独立运行两文件定向 **6/6**，日志／JSON `pdf-thumbnail-insert-current-20261113.*`；覆盖90/270度受控坐标和90度宿主，当时真实270度像素／长文裁切未验；后续真实短文本90/270专项见下方。agent 曾执行 `npm run build`（`tsc --noEmit && vite build`）写入默认共享 static，未保留终端日志；此事实与 root 上述隔离冻结构建分开记录，不将默认构建冒称冻结运行证据。
- [XLSX 系列／轴／交互命令盘点](NATIVE_XLSX_CHART_COMMAND_FAMILY_INVENTORY_20261113.md) 逐源列出控件、已证实闭环与剩余边界。scatter/radar 轴直接鼠标点选最初为确认缺口，后已补可见刻度／分类文本及真实单击验收；line/area 线段和填充区随后补了真实单击专项，精确范围见下方。
- Word 设置续补：来源 SHA 绑定的 `setTrackRevisions` 复用引擎原有 SaveOptions，受保护文档拒绝修改；inspect 回读后同步 recorder 和 Ribbon，草稿撤销／恢复保持相同设置。桥接 2 项、Python真实包 1 项、前端14项和 TypeScript 均由子 agent 终端确认（这些命令当时未保存独立日志）。真实发布回归发现 `NativeScope["userId"]` 会 TypeError，已修为 `.user_id`；下载真实 DOCX 中插入／删除的作者等于授权用户，validation失败仍保留链接。三组适用非阻断回归共7项通过。root 独立复跑新作者发布与设置真实包两个用例 **2/2**，日志 `word-settings-author-root-20261113.log`，不是用纯函数测试代替调用点验证。

## Three实际运行与当前分包收敛

旧 `static-lifecycle` 虽然预算通过，真实GLB插入却显示 `Cannot access 'gs' before initialization`；目录分包形成Three循环依赖。失败截图／日志保留，不能用打印通过代替3D通过。当前固定版本分组表的391份源码模块及14份产物分块图已独立核对；真实GLB→WebGL PNG→草稿成功，720×720图片独立回读111390个红色像素。

首次新构建还暴露Word render710.7 KiB、Workbook main378.8 KiB超限。根据模块审计抽离共享Fluent图标、图表面板和纯数据字体度量表后，新冻结 `/tmp/office-parity-convergence-20261113/static` 现有预算0失败、TypeScript exit0；最新冻结3D真实浏览器再次通过。旧失败与新通过分别归档，详见[Three专项的精确身份与边界](NATIVE_THREE_RUNTIME_ACCEPTANCE_20261113.md)。不外推所有四格式路径或完整保存周期通过。

## PDF真实旋转缩略图及Word命令族续记

PDF真实浏览器 `/tmp/pdf-static-text-thumbnail-20261113-run16/` 完成非零CropBox下90/270度短ASCII文字缩略图及实际预览去重。root目视三份截图，并独立用pypdf回读来源页面旋转／CropBox／MediaBox及来源SHA；74份实际资源逐SHA匹配隔离 `run5/static`。实际预览执行 `[0]`、无跳过，pending叠层0；页面／控制台／HTTP错误为空。结果及资源归档在 `pdf-insert-thumbnail-browser/`、`pdf-insert-thumbnail-static/`。长文本溢出在早期探针中被真实引擎跳过，不能据短文本通过关闭长文本、换行、字体或保存下载的证据空白，详见[PDF源盘点](NATIVE_PDF_SOURCE_INVENTORY_20261113_INCREMENT.md)。

[Word Review命令族逐源盘点](NATIVE_WORD_REVIEW_COMMAND_FAMILY_INVENTORY_20261113.md) 将已接通的批注子能力、拼写、修订设置与仍缺的标记过滤／范围菜单／story／比较保护等分开。新构建Word设置保存下载回读通过不改变这些缺口，完整目标保持active。

## 构建附属资源隔离更正

后续检查发现 `native-pdf-runtime-assets.writeBundle` 原来硬编码写共享 `../static/licenses` 和 `../static/pdfjs`，忽略Vite的隔离outDir。因此此前“隔离构建”只能准确表示主HTML／JS／CSS产物的位置，不能表示所有附属资源均未写共享static。旧资源身份与实际运行结果保持原样，不能追溯改写历史JSON中的错误措辞。

现已将同一插件的8个复制目标改为跟随Rollup `output.dir`；默认构建位置不变。新增 `src/vite-runtime-assets.test.ts` 先在Node环境准确复现目标错误，再1/1通过；最初jsdom收集阶段失败另存，不冒充有效RED。日志分别为 `vite-runtime-assets-red-node-20261113.log`、`vite-runtime-assets-green-20261113.log`。实际调用新插件复制203份许可证／cmaps／standard_fonts／wasm到 `/tmp/vite-runtime-assets-real-20261113`，共享附属目录全部文件的SHA、大小和mtime前后完全相等，`proof.json` 为ok。该项是插件实际执行与定向回归，不宣称已重新运行全部历史Vite构建。

## XLSX共享尺度及鼠标命中续验

Scatter x/y可见刻度和Radar primary分类文字已补，命中区与实际可见内容一致，隐藏轴不登记。root进一步发现新增尺度取整曾与源不同：`.152`应得到`.16`，`87`应得到`90`、`130`应得到`140`，不能使用粗略的1/2/5数量级上限代替。后续复用已有niceCeiling并按源majorUnit生成ticks，新增源向量先失败后通过；定向renderer116项与尺度共131项通过（子agent命令直接输出，无单独原始日志；不为补日志重跑），未重跑全项目测试。

更新冻结 `/tmp/workbook-axis-hit-static-source-scale-20261113` manifest `5d7d4d713d88818dacb2ec4766b641d67595c9016d799cecee5e19a20a8e95fd`，真实浏览器 `/tmp/workbook-axis-hit-browser-source-scale-20261113` 单击可见x/y刻度进入分类／数值轴；同一点先系列再数据点；Radar Q1文字进入分类轴。root独立复核298份实际资源SHA、草稿前后空、保存和planner均0、三类错误为空；旧final4证据与新源尺度版本分别归档，不混用点位。481个JS分块的现有预算无失败。该构建早于上方辅助资源插件修复，不能宣称整个共享static未被写入。

仅关闭上述鼠标／共享尺度范围。Radar quarter rings、nice最大值、类别上限／系列点clamp和完整散点格式仍按[命令族盘点](NATIVE_XLSX_CHART_COMMAND_FAMILY_INVENTORY_20261113.md)开放，不把所有图表视觉判为对齐。

随后在同一源尺度冻结资源上新增独立line/area夹具和浏览器专项 `/tmp/workbook-line-area-hit-20261113c`，未改生产代码、未重构建：折线段避开marker的中点单击命中series；marker先series再point；面积填充区单击命中series。root独立核对同一manifest、298份实际资源SHA、空草稿、保存／planner均0及三类错误为空，并目视三份截图。归档 `xlsx-line-area-hit/`，与源尺度静态资源对应；原先“只有marker、线段/面积未验”的证据空白在该明确子范围内关闭。没有因此证明修改颜色、保存回读或全部图表布局已完成。

## Word当前批注删除：首轮保存与同修订恢复

首轮真实浏览器已确认删除当前根批注并只保存一次，保存操作仅一项 `deleteComment`。Playwright `download.saveAs` 在 Snap Chromium 临时下载路径报 ENOENT，不能据此将成功保存说成失败或再次保存。随后 `/tmp/word-current-comment-delete-recovery-20261113` 从同一修订的下载地址通过实际HTTP读取字节并重开；该恢复阶段保存请求为0。API路由为夹具，DOCX变更使用真实Python/Node引擎，不代表生产授权或签发链验收。

root独立核对下载SHA `56b13a440903e29817b8254661983d7768310f9b57e0f0f17e3722311dec20d0`，ZIP没有新增或删除成员，仅 `word/document.xml` 与 `word/comments.xml` 变化；批注与三类锚点均删除，正文仍为 `Anchor text`。重开回读批注目标0；175份实际资源与冻结manifest `20775ab0532b3bd27e19a2bc64857d498e171007d3fbf1d2a20ae0cfefb0f00b` 对应资源逐SHA相等。证据归档 `word-current-comment-delete-recovery/` 与 `word-current-comment-delete-static-initial/`，保留恢复中的早期失败文件。

该证据仅覆盖首轮删除与恢复阶段。root另发现新按钮文案断行，以及面板存在未应用输入时先切换删除目标可能串写批注的问题。后续最小修复先应用原面板目标的输入，再切换到光标批注；从projected threads判断删除可用性，防止重复删除；新入口异常复用showError。控制器与Ribbon定向65项由子agent终端确认通过，不能用这些单测代替完整生产签发验收。

短文案“删除批注”在另一冻结构建 `/tmp/word-current-comment-delete-build-final` 中可见，完整无障碍标签仍为“删除当前批注”。该冻结manifest为 `ec1eb4fa2c5966a0710c71d93c2d33ebab32fedac717cd08c7df8dfb49025e92`；`/tmp/word-current-comment-delete-recovery-final-20261113` 再次只恢复同一修订，保存请求0。root独立核对175份资源、同一DOCX下载SHA与两个ZIP差异，目视短文案不再断行；归档 `word-current-comment-delete-recovery-final/` 和 `word-current-comment-delete-static-final/`。这次冻结早于随后脏输入与控制器异常处理修复，不能称为当前磁盘全部改动的完整构建验收；当前PDF并行改动导致的类型错误由PDF任务继续收敛。共享与隔离目录203份许可证/PDF.js附属资源内容相等只证明副本匹配；没有该次完整构建前后快照，不能单凭它宣称共享目录未被写入。

## Radar刻度环、类别上限与填充命中续验

本地Radar按固定源补四层quarter rings、1/2/2.5/5/10数量级最大值、primary类别数量3–12、短系列补零、超出类别的系列点截断与非负半径clamp。值环不登记为value-axis，保留完整系列polygon内部命中，不以缩成中心小圈来绕开系列与刻度环重叠。另将新Scatter尺度聚合中的参数展开改为迭代，200000点回归避免参数栈溢出。两个定向文件共135项由子agent终端确认通过，未为了补日志重跑。

新冻结 `/tmp/workbook-axis-hit-static-radar-20261113` 的manifest为 `441a2552065922f7cd0236fd31315721c9b2e9ac5a5e0a33c7855f9ee1ac959a`。真实浏览器 `/tmp/workbook-radar-browser-20261113-run7` 使用首系列13项、次系列15项的XLSX；root直接从ZIP回读引用分别为 `B2:B14` 与 `C2:C16`，核对实际画出的类别为Axis 1–12、299份JS/CSS资源逐SHA匹配、草稿前后空、保存与planner均0、三类错误为空，并目视四层环及12类别截图。系列内部点击进入series:1；名为outerRing的坐标接近外环，但尚未独立证明落在可见环线上，因此此记录不将其说成环线直接鼠标命中验收。原始run7和此前失败记录保持不变；归档 `xlsx-radar-run7/`、`xlsx-radar-static/`。

root对上述Radar与Word final两个新冻结分别执行现有预算函数，各483份JS、0失败，限额未改；记录 `office-review-radar-budget-root-20261113.json`。Vite能生成资源与全TypeScript通过是不同证据，不据该构建结果隐去当时PDF并行改动的类型错误。

root随后在同一冻结资源上补 `/tmp/workbook-radar-browser-20261113-run11`，通过捕获真实Canvas stroke顶点及drawImage离屏到可见画布的变换取得精确坐标，四环半径为37/74/111/148px。点击外环顶点 `(574,309)` 保持chart；系列内部 `(537,417)` 进入series:1，距中心54.49px、最近marker20.77px，排除只命中中心或marker的假通过。299资源、无草稿/保存/planner、三类错误为空均独立核对，两张目标截图目视确认；归档 `xlsx-radar-run11/`。run8–10的探针坐标映射失败另保留，不将其当作产品失败，也不改写run7原始JSON。现在仅关闭该直接无遮挡环线点击子范围。

Word另在包含脏输入/projected-thread/catch修复的新构建manifest `db769c2bae077ccf325f3fb7ed233c64e7ace1138127f65fbe613923121bc384` 下完成root浏览器续验 `/tmp/word-current-comment-delete-current-build-root-20261113`：同修订恢复、下载与重开，保存0、175资源匹配、正文与批注ZIP差异独立核对。它补的是新构建运行/重开证据，没有重复删除/保存，也没有把单测的跨目标输入场景说成浏览器已测。该冻结资源与精确边界见Word命令族盘点。

## PDF替换文字缩略图续补中的证据校正

该任务的收尾过程与后续受限验收分开记录。root先后指出并要求修正：直接叠文字形成重影；PDF.js用户空间坐标被二次反转；替换独立分支未设置cqw容器；detached DOM无法采样底色；仅看canvas宽度不能判断渲染完成；首个对象底色错误复用于同页全部对象。当前代码改为可信PDFium bounds覆盖、唯一水平PDF.js文字匹配、渲染成功后的逐对象采样及来源/代次检查，不引入新的持久化操作协议。

`/tmp/pdf-replace-text-thumbnail-20261113-final2/evidence.json` 与pending/actual-preview截图仅证明白底、显式蓝色覆盖的基础场景，不能证明彩色原字继承或浅色底采样。该旧探针没有完整资源SHA/错误数组及预览后叠层计数，不能据`ok:true`宣称完整通过。root另确认其HTTP预览模型缺少新增fillColor，而同一来源用隔离源码引擎读取即有 `[0,0,0]`：旧dist优先于源码，源码node:test通过不代表HTTP使用新bridge。只读源探针记录 `/tmp/pdf-replace-text-thumbnail-root-engine-20261113-source-inspect.json`；子任务正补隔离新bridge和彩色底/原字无显式覆盖的真实浏览器证据。上述旧证据须保留，不能追溯改写。

root随后执行当前前端 `pnpm exec tsc --noEmit --pretty false`，工具退出0、无报错，日志 `/tmp/office-parity-current-types-root-20261113.log`。较早PDF或邮件合并类型错误保留为历史阶段失败，不再表述为当前仍失败；这不改变旧冻结构建当时的类型检查状态。

后续 `final5/static` 的 Vite manifest 为 `6392e2d6c07a3c7b3a0e95bc35f24108ccea67c74d0d0341c3fc9ebf9af6ff59`。彩色探针 `color4/evidence.json` 虽写 `ok:true`，root目视 `pending-color.png` 发现宿主状态明确显示 `replacementOperations is not defined`：ready回调引用分支外不可见变量，底色赋值后即中断，cover没有更新。该错误被showError捕获，不会进入page/console/http错误数组，故原脚本不足以验收。root类型检查同时以2退出，确认TS2304和TS7006，日志 `/tmp/office-parity-final-pdf-types-root-20261113.log`；上一段类型通过只适用于更早状态。原始探针保持原样，独立拒绝说明与失败日志归档 `pdf-replace-thumbnail-prior-attempts/root-color4-rejected.json`，不把该轮当作通过。

root对该final5冻结执行现有预算函数，480份JS中两项超限：SlideThumb 303.8 KiB大于250 KiB、workbook-main 259.3 KiB大于253 KiB，记录 `/tmp/office-pdf-replace-budget-root-20261113.json`。未提高限额，也未将先前483分块构建的预算通过外推到该新构建；PPTX/XLSX分包问题作为独立未收敛项保留。

最终受限真实验收使用final6静态资源（Vite manifest `5cf73c83e35c10ad6dfe09a184f3cb3da5432303c50ebc919d4edad1c37bcf01`）与color5浏览器记录。root逐项核验77实际资源SHA、777文件起止清单、无显式font/color覆盖的单一操作、浅黄底与深蓝原字继承、实际预览执行 `[0]`/跳过空/两个镜像均0；目视截图不再有scope错误或白色cover。来源SHA为 `154ac7b15ec3d24a7fdfa861a1170d44de23de6bc637669464f55bdd1cb4b64c`，全静态清单摘要为 `913fdd180012a80c7fd3f1097c0b6645c13bd456a122ed2f16bb10897771c674`。详见[PDF受限验收](NATIVE_PDF_SOURCE_INVENTORY_20261113_INCREMENT.md)。归档 `pdf-replace-thumbnail-color/`、`pdf-replace-thumbnail-static/`；未做保存/下载或生产授权验收。

该次只覆盖rotation=0、UserUnit=1、唯一水平LTR单行文字，无styleRuns/colorRuns；旋转页、复杂字体/多样式和擦除补丁仍开放。ready回调在实际render promise成功后采样底色并重算ink，显式颜色覆盖优先；hide→show保留未执行订阅。final6预算检查仍为480份JS、相同两项超限，原限额未改；保留失败JSON，不能称当前全部检查通过。

同一final6资源后续color7浏览器加入pending/实际预览宿主状态与cover底色断言，root独立核对两截图、77资源与777文件，归档 `pdf-replace-thumbnail-color-final/`。新增真实宿主hide→cancel→show回归后，该文件5/5通过，日志 `pdf-replace-text-thumbnail-20261113-host-lifecycle-vitest-final.log`；root修正后TypeScript以0退出，日志 `office-parity-pdf-scope-fix-types-root-20261113.log`。未为了补日志重跑全项目测试。旧探针服务已清理，所有旧失败与原始JSON保留。Word/XLSX子agent并行只读复核了本批既有证据，root另确认Word归档实体并补明短名基准路径。完整四格式目标保持active，两个分包预算超限和各命令族剩余缺口没有被本批通过结果关闭。

## 批量批注、旋转替换、Scatter 与 Zoom 分包续批

本批详细记录见[续批验收](NATIVE_PARITY_NEXT_BATCH_ACCEPTANCE_20261113.md)，独立归档根为 `/home/junge/codex-evidence/smart_reporting/office-parity-next-batch-20261113/`。再次 `git pull --ff-only origin code` 已是最新，HEAD/origin/code 均为 `1138887d…`；保留已有 dirty 工作区。

- Word 补已解决/全部可信线程批量删除，保留文字/线程独立保存边界；fixture+真实 bridge 一次保存、下载、重开和独立 ZIP 回读通过，仅三处批注相关 part 改动。不是生产 HTTP 授权/签发验收。额外 recovery fixture 遇到的 50 项失败仍开放，未改无关 tracking 或重复整套恢复测试。
- PDF 受限 replaceText 缩略图续补非零 CropBox 下 0/90/180/270 页面旋转、layout∪ink 遮盖和源扩高规则。7 项精确 helper 和四页短文实际写回/预览去重通过；均匀底色逐页继承。长文溢出、窄色带背景采样、复杂字体/多样式和实际旋转字形与 pending 水平文字的差异仍明确保留。
- XLSX renderer 补 Scatter 边界 clamp、遵循源不应用 reversed；真实导入又发现双 valAx reader 缺口，按 plot axId 顺序复用原解析流程修复。严格浏览器验证自定义边界、隐藏轴、实际蓝色点、series→point 命中与草稿不变。原无 axes/透明 marker 的探针 `ok:true` 已拒绝为验收依据，旧证据保留。
- PPTX 将同步 Zoom validator 与懒加载缩略图网格分开，普通 CLI 实际 chunk 图无 model→grid 或 grid→main 拖入；真实候选 Canvas、插入 PNG、实际预览图片节点和撤销/重做通过。只验运行路径，未做 Zoom 保存下载重开。

第一次普通 CLI 冻结 manifest `4cf04bff…`、reader 修复后的第二次 `4d5fe933…` 均为485个JS原预算无失败；两次TypeScript/构建退出0，未提高限额。共享203个sidecars SHA/size/mtime未变。前述旧final6两项超限不追溯改写，后续预算收敛仅按这两份新构建记录。各格式证据绑定实际受测manifest，不把Word/PDF/PPTX第一次结果外推到第二次。完整穷尽目标仍active。
