# 四格式补缺续批验收记录

日期：2026-11-13。固定 GenOffice 源为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文件只记录本批列明的子范围，完整四格式穷尽目标仍为 active。

本批证据根目录：`/home/junge/codex-evidence/smart_reporting/office-parity-next-batch-20261113/`。下述归档短名均相对此目录。

## 同步与第一次冻结

`git pull --ff-only origin code` 返回 `Already up to date`；`HEAD...origin/code` 为 `0 0`，提交均为 `1138887df2541b748ebe5746871e4198bb48a712`。未清理已有工作区改动，未提交或推送。

普通 CLI 构建输出到 `/tmp/office-parity-next-batch-20261113/static`，归档为 `static/`；manifest SHA-256 为 `4cf04bff9c8d1a7a0b4a285cf7e6590dab2a0a437f626da05f15957cc1e680fd`。`pnpm exec tsc --noEmit --pretty false` 与 `pnpm exec vite build --outDir …` 均退出 0。485 个 JS 分块通过原预算，未修改限额。共享 `licenses/`、`pdfjs/` 的 203 个文件在构建前后 SHA、大小及 mtime 完全一致；10 个受控生产文件的冻结 SHA 也未变。日志与逐项清单见根目录 `office-parity-next-batch-*.json` / `.log`。

此前带审计插件的 Node API 构建只用于诊断，不代替本次普通 CLI 预算结果；旧 final6 两个超限结果仍保留，不能追溯改称通过。

## Word：删除已解决批注与全部批注

本地 Review 的两个批量入口复用可信来源线程和 projected 状态；根线程删除级联回复，任一成员不可删则整批禁用。一次确认后以一个 ProseMirror 事务写入 source-bound 删除 intents。已解决筛选读取当前草稿状态；已删除根不会重复加入。

未应用批注文字先 flush。既有保存协议禁止批注文字和线程操作混批，因此有文字草稿时明确提示“批注线程修改需独立保存，请先保存批注文字”，不丢输入、不继续删除。本批没有放宽保存协议。

浏览器 `/tmp/word-comment-batch-browser-20261113` 使用第一次冻结资源完成已解决删除、撤销、全部删除、一次保存、HTTP 下载与修订 2 重开。该 smoke 使用本地 API fixture 和真实 Python/Node DOCX bridge，**不等于生产 HTTP 授权或签发链验收**。

- 来源包含两个根和一个回复；保存请求为 1，下载为 200，重开可信批注目标为 0。
- 下载、磁盘修订与回读 SHA-256 一致：`5ecb530eb4bd7ae4ebe16a6c552e021c5cf72c888bb22fc4dd93f5e6d1f7703b`。
- root 独立 ZIP/lxml 回读：仅 `word/document.xml`、`word/comments.xml`、`word/commentsExtended.xml` 改变；正文 `Anchor text` 保留，全部批注/锚点清除，回复 id `2` 的三类锚点同时删除。177 个实际 JS/CSS 响应逐 SHA 匹配冻结磁盘。
- root 目视全部删除草稿和重开截图，相关按钮禁用符合目标为空的状态。
- 首轮启动失败是默认 Playwright 浏览器缺失，`failure.json` 明确 `saved:false`；随后指定 `/snap/bin/chromium` 成功。两次启动记录保留，未重复已成功的保存。

控制器/Ribbon 首轮两个目标文件为 19/19、48/48（子 agent 终端结果，无独立原始日志）。`word-comment-batch/` 中新增聚焦日志为 `word-comment-batch-browser-20261113-vitest.log`：dirty flush、projected resolved 和 Ribbon 接线共 3 passed、66 skipped；权限、取消及原子历史新增断言另以 `word-comment-batch-browser-20261113-atomic-test.log` 单项验证，1 passed、20 skipped，不把 skipped 当作通过。

曾额外执行 `docx-recovery.test.tsx`，62 项中 50 失败、12 通过，失败集中于 fixture 中 `editor.storage.trackChanges` 未定义。该失败保持开放；未为此修改无关 tracking 生产逻辑，也未重复整套恢复测试。

## PPTX：Zoom 同步校验与懒加载网格分包

`slides-zoom-model.ts` 的同步草稿校验和 `slides-zoom-grid.tsx` 的缩略图 UI 分为两个 chunk。单项配置回归先 RED 后 GREEN，日志为 `office-zoom-chunk-boundary-{red,green}-20261113.log`。普通 CLI 的实际 manifest 再核对：model 无 imports；网格的 11 个传递依赖中没有 slides-main；main 仅动态引入网格。详见 `office-zoom-chunk-graph-final-20261113.json`。

`pptx-zoom-runtime-final/` 使用第一次冻结资源、已有隔离 PPTX engine，完成真实 HTTP 导入三页 PPTX、两候选实际 Canvas 网格、取消不产生草稿、重新打开并插入 PNG 快照、实际 render-tree 回读和画布显示、撤销/重做恢复同一草稿。

- 快照为 1920×1440，独立像素回读 40794 个非透明深色像素；实际 render-tree 包含同一 PNG data URL 的图片节点，root 目视插入后的画布。
- 169 个实际资源响应逐 SHA 匹配冻结磁盘；保存/新修订为 0，page/console/HTTP 错误为空。
- `pptx-zoom-prior-without-preview-wait/` 的初次探针虽验证了 PNG 和草稿，但截图早于异步实际预览完成，不能用它证明最终画布已显示；随后只增强 smoke 的等待和实际节点断言，并使用新目录续验。

本项只关闭所列分包及运行路径，不证明 Zoom 保存、下载、重开和所有目标/分节组合。

## PDF：非零 CropBox 与四种页面旋转

`pdf-replace-text-thumbnail.ts` 将唯一水平 LTR PDF.js 文字项的 baseline、advance、ascent/descent 还原为 PDF-space layout rect，再投影到页面显示坐标。layout 与可信 PDFium ink bounds 合并后作为 cover；按固定源宽度增长、向上扩高和 flex-end 规则显示单行替换，保留身份/摘要、UserUnit=1、无样式 run 等限制。0°原先的盒也随源扩高规则修正，不声称旧几何完全未变。

非零 CropBox helper 精确单测为 7/7，日志 `pdf-logs/pdf-replace-text-thumbnail-vitest-20261113-crop.log`。真实 Chromium 使用第一次冻结资源，最终运行 `/tmp/pdf-replace-rotations-browser-20261113-uniform-verify`，归档 `pdf-replace-rotations-final/`：

- 来源 SHA-256 `d5d6a7fbee4a5b8cfd4580d15d6371774557142dcafc491605b19f99c505b7ae`，四页 rotation 分别 0/90/180/270，CropBox `[20,30,280,370]`、MediaBox `[0,0,300,400]`。
- 每页整张 CropBox 均匀底色分别为 `#FFF2CC`、`#E2F0D9`、`#DDEBF7`、`#FCE4D6`。pending overlay/cover 逐页精确匹配底色，并继承 `#123456` 原字色；未指定颜色/字体 override。替换文案为 `New 1` 至 `New 4`。
- 四页 actual/expected overlay 与 cover 的浏览器矩形均写入 evidence，最大屏幕误差约 0.0153px。root 另用 PDF.js 独立读文字项和字体指标，按固定源公式验证四页 layout left/top/height 与 union-cover，最大误差 0.00012 PDF unit，见 `root-independent-layout-proof.json`；文字宽度增长另由 helper 与浏览器投影验证。
- 实际 PDF 预览执行 `[0,1,2,3]`，无 skipped，实际回读四条新文字且颜色一致；进入实际预览后两类 pending 叠层合计为 0。77 个资源响应逐 SHA 匹配冻结磁盘，page/console/HTTP 错误为空。root 目视 pending 与 actual 两图。
- 此运行的全目录文件清单 digest 为 `4cc4f662c4786bfef1d6299f5e4e19b90e182e16d66228778fcd0c6d36568020`；它**不是** Vite manifest SHA，不与第一次冻结的 `4cf04b…` 混用。

失败尝试保留：首次目录已有文件冲突、随后把 computed px 误作百分比的探针错误；长 `Replacement N` 被实际引擎以 `pdf_text_overflow_or_unverifiable_output` 跳过；窄色条的 ring 采样在 180°变浅、270°采到白纸。最终均匀底色用例不关闭这些复杂背景/长文本限制。

固定源 pending 文本保持显示空间水平，cover 只遮原 layout∪ink，不随文字扩宽；90/270°的 pending 文字可能超出细长原区域。此处只按源规则关闭四种旋转的受限几何/短文执行范围，**不声称 pending 与实际旋转字形逐像素一致**，也不证明保存、下载或全部 PDF 文字样式。

## XLSX：Scatter 自定义边界和双数值轴读取

renderer 的 x/y 刻度与点共用 clamp 映射，超出显式边界的点停在绘图区边缘；固定源不应用 Scatter 的 reversed，故不擅自翻转数据。原始 x/y、系列/点索引和 hit identity 保留，隐藏轴不画刻度/注册轴区域，不改变点坐标。

真实导入进一步发现 reader 的 `axesOf` 白名单漏了 Scatter，导致 store 没有 axes；这是真正源码缺口，不是旧 dist。最小修复只扩展原轴解析流程，按 scatter plot 声明的两个 axId 顺序映射 X/Y `valAx`，复用重复 ID、crossAx 和字段解析校验，不按 XML 轴对象出现顺序猜测。原 dirty reader SHA `f9930a788810456d9f5bed6bc8ecfeb71770d725695f62043d2094bde464d4c1`，新 SHA `dacda015f3df614e51dd554691c39b2d2c2b0bda507b6d67af31647936dc12c2`；root 从最小反向变更重建旧文件并核对原 SHA，归档 `scatter-reader-only.patch`、before/after 和 integrity JSON。

renderer 新增聚焦用例为 6 项通过；reader 两个定向文件 20/20，通过倒序 XML 双 valAx、显式边界、majorUnit、reversed、hidden 与 series refs 的真实 OOXML 读取。以上来自子 agent 终端原输出，无独立日志，不为补日志重跑。首次 RED 夹具曾缺 categories，修正后才以 axes 缺失得到有效 RED，不能把夹具输入错误算作产品失败。

reader 修复后另以普通 CLI 冻结 `/tmp/office-parity-scatter-reader-20261113/static`，归档 `static-scatter-reader/`，manifest SHA `4d5fe933b0a0d9d23e628ecff6245ca8a9e3d827dfec92f1871e75321db8ebed`。root 新 TypeScript/构建均退出 0，485 个 JS 原预算无失败；第一次冻结的十个生产文件和共享 203 sidecars 仍未变。Word/PDF/PPTX 前述运行继续引用各自实际的第一次 manifest，不冒称在第二次构建上重跑过。

strict Chromium 运行 `/tmp/workbook-scatter-browser-20261113-reader`，归档 `archive/xlsx-scatter-final/`：

- 实际 store 的 X/Y 两轴 min/max 均为 -10/10，majorUnit=10、reversed=true；两图分别 visible 与 hidden。没有用脚本注入 store 代替真实导入。
- 实际 Canvas/offscreen drawImage 变换后，可见图三点为 `(142,611)`、`(486,457)`、`(830,303)`；隐藏图为 `(934,611)`、`(1278,457)`、`(1622,303)`，各自归一化均为 `[(0,1),(.5,.5),(1,0)]`。
- root 目视并独立读取最终截图：可见图三点和隐藏图首点各有 12 个精确 `#4f81bd` 像素；其它隐藏图点在面板后/视口外，其坐标由实际 Canvas 绘制记录验证，不假称截图全部可见。
- 实际点击依次命中 `series:0`、`point:0:0`；隐藏轴原区域命中 chart。草稿前后均为空，保存/planner=0；301 个实际资源逐 SHA 匹配，三类错误为空。root 独立证明为 `root-independent-proof.json`。

首轮选择器失败和 retry1 的误通过均保留：透明 marker 夹具加上 reader axes 缺失时，单凭 Canvas arc/`ok:true` 不足以验收。最终移除透明设置并强制检查 store axes、可见色及真实坐标后才关闭本子范围。完整 Scatter 的线型、gridlines/displayUnit、复杂格式与保存往返仍开放。
