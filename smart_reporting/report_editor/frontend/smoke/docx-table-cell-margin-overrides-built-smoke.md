# Word 所选单元格边距覆盖 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-cell-margin-overrides-built-smoke.mjs
```

默认端口4242，支持 `DOCX_CELL_MARGIN_OVERRIDES_SMOKE_PORT`。只启动 vite preview，不构建；等待root最终统一frontend与doc_engine bridge产物后运行。旧默认边距、alignment等已验收probe不重复。

四来源：普通三行表；firstRow条件table style右151与首行tblPrEx上23/左41/下17继承叠加；2×2合并owner无直属tcMar但hidden continuation有left71覆盖并含隐藏中文；bidiVisual与首格竖排。所有来源保留末行作为非目标对照，奇数网格1801/2401/3001、整表默认T/L/B/R=0/108/7/109，以及中英文/emoji、rsid、混合runs、底纹和空段落。

公开“表格属性”打开标题“单元格边距”的有限属性UI。caret无操作精确显示奇数twip；真实鼠标CellSelection混合矩形左边留空并显示“多个值”，不填写确认不变。合并来源先执行仅hidden有覆盖的恢复继承，随后每源连续矩形setA、首owner reset、首owner setB、首owner reset，重复reset必须无操作。setA四边为0/176/96/130twip，setB为20/180/100/145twip；保存必须保完整有序steps（普通/继承/bidi竖排4步，merged5步），不得折叠成最后一步。

用真实内容盒和computed padding验证set改变布局，reset首owner的left严格取签发resetEffective（再按来源table/Word默认补缺边），继承来源必须实际恢复row left41/top23/bottom17及style right151。UndoRedo精确DOM、草稿刷新、项目Python patch、真实HTTP下载与SHA、ZIP回读、明确修订重开geometry全部核对。回读各owner effective/rawPresent/hasPhysicalOverrides与有序steps重放匹配；仅mask tcMar后整个document.xml逐字相等、所有物理cell非tcMar全文/所有段落（含hidden）/末行非目标cell全文/其他ZIP parts身份全部保持，整表默认不动。所有加载JS须HTTP200与本地SHA一致，console/pageerror空。

授权/修订路由为本地夹具；实际DOCX inspect/patch调用项目Python接口，下载经过临时真实HTTP服务。本证据不代表生产授权HTTP、桌面Word或PDF排版等价。

最终构建 `/tmp/office-overrides-trace-build.log` 后实测完成。首轮普通来源完整保存为修订2，产物 `/tmp/docx-cell-margin-overrides-built-us3sxn/`：`downloaded-revision-2.docx`、`revision-2.docx`、`revision-2-overrides-reopened.png/.html`。其全部断言已通过；后续继承fixture预检错误终止首轮，日志保留 `/tmp/word-cell-margin-overrides-built-first.log`。该fixture误用固定parser不读取的style直属tcPr；改为真实支持的firstRow tblStylePr及tblLook，helper真实inspect确认resetEffective为 `{top:23,right:151,bottom:17,left:41}`，未改产品或放宽继承断言。

用 `DOCX_CELL_MARGIN_OVERRIDES_START_REVISION=10` 仅续跑剩余三源，session73068终态exit0，日志 `/tmp/word-cell-margin-overrides-built-smoke.log` 为 `ok=true/errors=[]`。产物 `/tmp/docx-cell-margin-overrides-built-ZNUz4R/`，继承/merged/RTL竖排分别保存为修订11/21/31；每份均有真实下载DOCX与重开PNG/HTML。连续步骤分别4/5/4，普通4步已在首轮完整断言；set/reset、混合矩形不填、无操作、UndoRedo/draft、Python实际patch、HTTP下载SHA、严格XML/ZIP身份、明确修订重开全部通过。未重复普通浏览器或旧专项probe。

布局证据：继承owner set后左/右padding为8.667px/11.733px，reset实际恢复2.733px/10.067px（row left41、firstRow style right151）；签发resetEffective及保存重开仍为上23/右151/下17/左41。merged owner的hidden-only覆盖先reset仍签发第一步，后续set/reset恢复默认7.2px/7.267px，隐藏正文逐字保持。RTL竖排owner恢复默认左7.2px且内容盒位置实变，最终geometry精确重开一致。121个JS的HTTP200/本地SHA均通过，bundle身份保存在最终JSON的loadedChunks；非tcMar XML、所有段落/隐藏正文、非目标末行及非目标parts全部保持。UI agent已目视继承修订11截图。

当前bundle SHA清单及四份实际下载SHA另存 `/tmp/word-cell-margin-overrides-built-evidence.json`；后续其它专项重建不改变本轮已验收产物证据。
