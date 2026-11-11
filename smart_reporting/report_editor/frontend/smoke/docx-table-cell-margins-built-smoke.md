# Word 整表默认单元格边距 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-cell-margins-built-smoke.mjs
```

默认4242（`DOCX_CELL_MARGINS_SMOKE_PORT`），只用root最终frontend/独立doc_engine bridge构建，不build。普通、横纵merge+hidden continuation独立tcMar、bidiVisual、竖排四来源；原整表T/L/B/R=0/108/7/109，owner局部覆盖left33，continuation独立left71。

公开dialog默认pt精确显示109twip=5.45pt；无操作确认DOM不变；显式cm输入right0.31→176、bottom0.17→96、left0.23→130、top0，保所有physical tcMar/content。每源undo/redo、草稿刷新、save→项目Python patch→真实HTTP下载/SHA/ZIP回读→明确修订重开，真实内容盒变化并重开一致。只mask直属tblCellMar后整XML逐字相同，cell XML全文（含override/hidden/段落rsid/runs/方向/宽高）及其他parts SHA全等。JS200+SHA，console/pageerror空。

来源保真适配：source中间2位cm会无操作量化108/109；本地以整数twip内部存储，pt精确显示，未编辑字段直接capture，单位输入复用parseTwips，避免无操作量化。不扩展Cell页覆盖/清除范围；本按钮只改整表默认。

最终统一构建后首轮实测通过（exit 0），日志 `/tmp/word-cell-margins-built-smoke.log`，产物 `/tmp/docx-cell-margins-built-jQTQuL/`。普通、merged、bidiVisual、竖排四来源分别保存为修订 2/11/21/31，四次 operation 均为 `setTableCellMargins`，值 `{top:0,right:176,bottom:96,left:130}`；真实下载 SHA、所有 physical cell XML、mask 默认边距后的 document XML、其他 ZIP parts 均通过。`cellOverridesPreserved=true`、`onlyTableDefaultsChanged=true`、121 个加载 chunk 的 HTTP/SHA 检查通过，`errors=[]`。

布局证据：普通默认格左 padding 从 7.2px 变为 8.667px，右 padding 从 7.267px 变为 11.733px；显式 left33 的 owner 保持 2.2px。merged owner 高度从 208.09375px 变为 219.96875px，竖排首格内容左偏移从 71.109375px 变为 86.421875px；四来源保存重开后的 geometry 均与修改后精确相等。已目视修订 11 和 31 的重开截图，合并结构、竖排及中英文/emoji 内容保留。无操作确认、undo/redo、草稿刷新也全部通过；未重复 alignment 或旧功能 probe。
