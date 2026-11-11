# Word 单元格文字方向 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-cell-text-direction-built-smoke.mjs
```

默认4242（`DOCX_CELL_DIRECTION_SMOKE_PORT`）；只用root统一构建，不build。普通富文本中文emoji/多段/尾空、复杂横纵合并+隐藏continue+tbRlV原别名、缺首格tcPr来源。三个来源逐方向真实公开按钮：tbRl/90°→btLr/270°→横排清除，每步保存/HTTP下载/ZIP回读/明确修订重开再继续，共9次真实保存。

DOM验证computed writingMode为vertical-rl/sideways-lr/horizontal-tb，Text Range前三个字符实际rect均非零；截图供目视。首次rotate验证undo/redo精确DOM，草稿刷新精确恢复；别名有效方向已相同不承诺视觉变化，但实际保存需写标准方向。仅caret逻辑owner，merged涵盖restart及物理continue，非目标方向不变。

只移除方向元素后整XML逐字保持（缺tcPr新增的空容器一并屏蔽），其他parts SHA与物理格身份保持；宽/grid/rowheight/marks/段落rsid均不脱敏。下载SHA匹配修订、JS200/SHA匹配本地assets、console/pageerror为空。准备Node语法和嵌入Python compile通过；尚待最终build执行。

最终 built 实测（2026-11-10）首轮session73422 exit0，`/tmp/word-cell-direction-built-smoke.log` 为 `ok:true/errors:[]`；Chromium140.0.7339.16，产物 `/tmp/docx-cell-direction-built-p1RPVx/`。9次真实保存/HTTP下载/ZIP回读/修订重开全部通过，未放宽断言、未重试或生产重建。

三来源computed writingMode依次vertical-rl、sideways-lr、horizontal-tb；真实字符Range rect：普通A1前两字符90° y432.625→442.625，270° y512.890625→502.046875；横排x492.5→502.5，明确真实推进轴及正反方向。undo/redo/draft精确DOM、原tbRlV显式编辑标准化、merged restart+continue同步、horizontal删标签、缺tcPr插入均通过。方向外整XML字节、非目标parts SHA与cells身份完整保持；JS200且SHA匹配最终assets。

截图及HTML：普通修订2/3/4、复杂merged修订11/12/13、缺tcPr修订21/22/23各有 `revision-N-direction-reopened.png/.html`。已目视rev12（270°左侧MERGED两段反向旋转，右侧C1/C2水平不变）与rev13（横排恢复，中文emoji/混合格式及表外段完整）。隐藏continue不显示但原内容字节已严格验证保留。

UI证据：`/tmp/word-cell-direction-ui-red.log`首次缺module RED；`/tmp/word-cell-direction-ui-green.log`5项GREEN；`/tmp/word-cell-direction-ui-guards-green.log`新增无表/新表/反向混编1项GREEN；最终`/tmp/word-cell-direction-ui-types.log` exit0。共6项分别验证，未重复完整测试。API无需normalize，baseline别名有效方向由engine解析保留rawTcPr。
