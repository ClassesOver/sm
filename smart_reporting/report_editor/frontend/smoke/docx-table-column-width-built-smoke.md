# Word 列宽与均分列 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-column-width-built-smoke.mjs
```

port 4241（可用 `DOCX_COLUMN_WIDTH_SMOKE_PORT` 覆盖）；仅使用 root 最终已构建的 frontend/bridge，脚本不构建、不运行其他测试。实际下载由随机127.0.0.1临时HTTP端点供给并在finally关闭，避免Playwright route下载 canceled；仍真实点击公开下载链接并读取Download.path校验SHA。

自含真实 DOCX fixture 为2×3固定dxa表，grid `[1801,2401,3001]`、tblW=7203，页面12000twip、左右margin1500（正文上限9000）；每格含段落rsid、pPr、混合粗体颜色/斜体runs、中文emoji、多段尾空、主题shd以及pretty XML空白。另一来源包含横跨2列/纵跨2行的restart与保有隐藏文字、主题tcPr的continue；第三份为多栏readonly来源。

公开UI流程：首单列设3000→撤销/重做→caret单列均分全表（`[2801,2801,2800]`）→首列设3300→真实鼠标选前两列局部均分（`[3051,3050,2800]`）→草稿刷新→公开save→真实Python patch→实际HTTP下载→ZIP回读→明确修订2URL重开。断言DOM data-colwidth×15等于真实inspect整数grid，不能用截断后视觉近似代替。合并来源caret设1500必须覆盖两逻辑列，保存/下载后`[1500,1500,3001]`，修订11重开；额外验证超大30000请求fit后不突破9000、undo恢复，多栏列宽和均分按钮明确readonly。

严格回读：tblW=sum(grid)、每个物理tcW=sum(span宽)包括continue；只脱敏tblW/gridCol/tcW的w:w值后整个document.xml逐字一致，原段落片段/顺序、隐藏continue、tcPr/trPr、表外XML及所有其他parts SHA均保持；逻辑格rect/物理坐标不变。JS200与本地构建SHA一致，console/pageerror为空。路由仅替代授权/修订存储，inspect/patch/ZIP为真实项目Python实现。

Node语法与嵌入Python compile检查完成；root最终构建包含初始/重开可信奇数twip归一化后，已执行严格built验收并通过。失败保留stage、截图/HTML；成功输出实际operations、SHA、构建身份及产物目录。

## 最终 built 实测（2026-11-10）

首轮 `/tmp/word-column-width-built-smoke.log`，session `68939` exit1，产物 `/tmp/docx-column-width-built-wF7g2X/`：set3000成功、undo成功，但probe在undo和redo中间点击Ribbon tab夺走键盘焦点，redo未派发。只移除该无关点击，并增加undo必须精确恢复`[1801,2401,3001]`的断言，没有放宽任何宽度/保存断言，没有改生产或重建。

必要重跑命令：`node smart_reporting/report_editor/frontend/smoke/docx-table-column-width-built-smoke.mjs > /tmp/word-column-width-built-smoke-rerun.log 2>&1`，session `44702`，exit0。Chromium `140.0.7339.16`，完整JSON位于该日志；实际源/修订/下载DOCX及截图/HTML位于 `/tmp/docx-column-width-built-tanTUM/`，最终多栏只读截图 `multicol-readonly.png`。

全部通过：单列宽度undo/redo、单列均分整表、多列局部均分、草稿刷新、真实Python保存/HTTP下载、修订2与复杂合并来源修订11重开、DOM colwidth精确匹配inspect整数grid、complex continuation隐藏文字/属性保留、页面9000上限、多栏readonly、脱敏宽值后document.xml逐字相等及其他parts字节相等；`errors=[]`。
- `sourceSha256`：`f0ae14c19ec80f0a3a6775a795cdf99b9f0bfc268d4a92fe0e3258c0636e72b8`。
- `downloadedSha256`：`f72cbf02548384575c393def950c5393b2a94075c5bef8dfa0c03bafd7d225a8`。
- `mergedSourceSha256`：`da1ef9f045c13eb772e513d68b15ae8d24fc088eec30a0aad2c2ec79bda2b6a8`。
- `mergedDownloadedSha256`：`6b90fd7f4490183eeded7ddef4d70ee48ec5a91d6014bc7f7f87902d6498a4b2`。

加载JS均响应200且SHA匹配本地构建；关键资源：
- `lazy-native-docx-table-column-width-CNhBoRb7.js`：`3cbb82061631697211f2ff00656abc718acee8e7052a9595a7ea9c2fee7ac427`。
- `lazy-docx-main-BY1ua6vz.js`：`122dbf0a56e7406cbaef9122fe55d2ca205931ef09f0695ec02f355f7c34ad41`。
- `lazy-native-docx-engine-fi36lBWH.js`：`0d082be303183e213e42848358ea30d0935e38a1e4ebdd0957af2302cb13c68c`。

补充最终效果图：仅以已保存的 revision-2.docx / revision-11.docx 快速重开截图，没有重复编辑保存流程；独立 `/tmp/word-column-width-reopen-screenshots.mjs`，session `32665` exit0，日志 `/tmp/word-column-width-reopen-screenshots.log` 为 `ok:true/errors:[]`，并再次断言DOM widths等于inspect。原产物目录新增 `revision-2-column-width-reopened.png/.html`、`revision-11-column-width-reopened.png/.html`。目视复核修订11显示合并来源左侧与右侧C1/C2、原中文emoji混合格式；continuation隐藏内容仍不展示但实际XML已严格验证保留。
