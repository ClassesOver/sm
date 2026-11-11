# Word 表格标题/说明 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-alt-text-built-smoke.mjs
```

独立默认端口4269，可设 `DOCX_ALT_TEXT_SMOKE_PORT`。只启动vite preview，**不build**；必须等root对包含最新parser raw解码和textarea CR/CRLF noop修复的新dist及预算明确放行。最终统一dist已由root完成build、预算与contract检查；真实built专项通过，证据见末段。

四来源、恰好四次有意义保存：

| 来源修订 | 选择与原值 | 保存最终值 |
| --- | --- | --- |
| 1 missing-props | caret；缺失整个tblPr | 中文/XML符号标题，LF多行说明及字面`&#10; &#13; &#9;` |
| 10 paired-whitespace-title | 鼠标首行矩形；成对标签，标题首尾空白 | 只改标题，保留原LF说明及字面字符引用 |
| 20 merged-description | 跨两行owner可见下部真实点击 | 只改说明，保留原标题；隐藏continuation、所有cell原字节 |
| 30 rtl-floating-clear | caret；RTL及浮动定位；说明含真实CRLF/CR | 清空两个标签 |

每来源先从table-properties→table-alt-text公开导航，核对单行标题/多行说明。未改确认须保持canonical DOM及localStorage草稿原值；CR/CRLF按textarea标准显示成LF，但不得因此创建操作或丢弃原raw。真实表格手柄（首段居中滚动后hover/click）须产生裸NodeSelection（可见selectednode），Alt入口禁用；再真实点击cell重新进入，不注入PM/debug选区。之后改值、Undo/Redo并通过属性dialog回读证明Alt值恢复；单看不可见metadata的DOM不足以证明Undo。刷新草稿重选后验证最终值、完整canonical DOM及实际geometry/CSS/正文一致。

保存使用项目真实Python patch，HTTP下载SHA匹配实际保存字节；操作必须严格为一个`setTableAltText`完整title/description值对。ZIP回读只mask直属tblCaption/Description两标签；缺原tblPr的来源仅额外归一因新增标签必需的空tblPr壳，其它document.xml及所有cell XML、非document ZIP部件必须一致。lxml标准属性解析器及项目source model均核对最终值，证明LF与字面`&#10;`不会串义。明确新修订重开再核对属性值、真实geometry/CSS/正文，保存截图与HTML。

所有cell保留tcFitText、unknown sibling，merged continuation包含独立隐藏正文；grid2001/1999、段落rsid、RTL和浮动定位不得变化。merged下部点击仅覆盖owner下部真实caret，不声称独立lower逻辑slot。只保存DOCX替代文字，不声称浏览器renderer已生成完整ARIA语义，也不声称桌面Word/屏幕阅读器/PDF已验收。授权路由使用本地夹具，不冒称生产授权HTTP；保存、下载和标准XML回读为真实。

`DOCX_ALT_TEXT_RESUME_DIRECTORY`指向前次目录时逐来源读取result与下载文件、核验SHA后直接复用已过结果，不重复保存。`DOCX_ALT_TEXT_START_REVISION`仅续指定及以后未通过来源。每来源完成即时写`{name}-result.json`并打印revision/SHA；失败保留failure.html/png和stage；成功含四结果/operation、全部实际加载JS的HTTP200+本地SHA及console/pageerror=[]。不重复旧专项或完整测试。

准备夹具为 `/tmp/word-alt-built-prepared-{missing,paired,merged,rtl}.docx`，capability均true；paired和RTL原多行/字面字符引用由lxml与source capability双重回读确认。最终built证据见末段。

首次built探针在`node-selection-missing-props`失败（`/tmp/word-table-alt-built.log`、`/tmp/docx-alt-text-built-8LDWdp/failure.html`与`failure.png`）；原因是探针误用本来pending的`table-select-all`，不是产品标题/说明失败。仅改为与对齐专项一致的真实表格手柄点击，保留裸NodeSelection与Alt禁用断言；无成功case、无保存。等待root预算通过的新dist放行后继续。

最终通过：冻结dist上session68376 exit0，`/tmp/word-table-alt-built.log`为`ok=true/errors=[]`，四来源四次保存到修订2/11/21/31。完整manifest `/tmp/word-table-alt-built-evidence.json`；下载、结果、重开截图/HTML `/tmp/docx-alt-text-built-VA6zov/`。121个实际JS资源HTTP200与本地SHA一致，四下载SHA再次读盘核对。Undo回读关闭dialog后通过真实点击cell恢复焦点，并断言编辑器包含activeElement再按Redo；保留全部Undo/Redo值断言。焦点探针失败`/tmp/word-table-alt-built-focus-red.log`发生于保存前，与首轮pending按钮失败均0保存；最终仅首次四次有意义保存，无重复完整测试。完整范围及限制见`../../NATIVE_WORD_TABLE_ALT_TEXT_ACCEPTANCE.md`最终段落。
