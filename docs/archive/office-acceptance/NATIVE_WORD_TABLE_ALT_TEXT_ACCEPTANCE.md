# Word 表格标题／说明验收（built 专项通过）

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`，真实入口/24次保存调查见 `NATIVE_WORD_TABLE_ALT_TEXT_INVESTIGATION.md`。本项只修改直属 tblCaption/tblDescription，不重建表格，不添加题注编号或完整无障碍语义。浏览器built专项已完成，最终证据见末段。

协议 setTableAltText 只接受 kind/blockId/expectedObjectSha256/title/description，完整最终值对，重复操作替换intent；Unicode codepoint标题255、说明4096上限，trim，标题禁CR/LF/TAB，说明允许标准多行，XML非法控制符和surrogate拒绝。PM只改tblCaption/tblDescription/nativeTableAltText，不开放tblAltEdited；同表文字/结构/样式操作互斥。

独立core/project3项GREEN `/tmp/table-alt-text-green.log`，bridge4+parser2共6项GREEN `/tmp/table-alt-text-parser-final-green.log`。局部parse.ts在现成attachRawTablePr路径对两个raw属性复用decodeEntities（先numeric后named）只解一次，修复数字换行但保留literal `&amp;#10;`。单双引号、属性等号空白、paired/selfclose、值含大于号、空值覆盖。实际保存产物 `/tmp/table-alt-text-implementation/` 经引擎、renderer PM和标准lxml回读中文/XML符号/LF/CR/TAB/literal references一致，parse hash及来源说明已登记。

Python初始cap缺失RED `/tmp/word-table-alt-python-red.log`；root接cap/hash/保护/strict keys/整批互斥/局部XMLsave/最终索引回读/core metadata保留，独立bundle `/tmp/word-table-alt-integrated-bridge-build.log` exit0，9项GREEN `/tmp/word-table-alt-python-green.log`。包括标准XML与source多行回读、literal reference不双解码、隐藏continuation/tcFitText和全部非目标ZIP保持、非法值/hash/保护/同表批次拒绝。

collector/replay2项GREEN `/tmp/word-table-alt-operations-green.log`：完整最终值投影、字段/hash拒绝、同表操作和伪造cell几何拒绝。UI4项GREEN `/tmp/word-alt-ui-final.log`、窄types `/tmp/word-alt-ui-types.log` exit0：独立属性导航、未动原raw空白no-op、trim/clear、UndoRedo、stale doc/selection/anchor、保护/嵌套/长度/旧target互斥；裸NodeSelection按源拒绝。统一构建和实际下载重开仍待完成。

受影响旧投影13项GREEN `/tmp/word-table-alt-mutual-regression.log`。独立集成review `/tmp/table-alt-text-integration-review/result.json` 实际逆序两表+段落增删+section marginLeft2500，missing tblPr/paired属性、中文/LF/CR/TAB/literal refs在引擎与标准lxml一致，物理隐藏续格和非目标parts保留；tblPrChange只读，前项有效末项title超长CLI exit1且output不存在。未用重复完整测试代替独立取证。后续UI还需核对textarea对初始CR/CRLF归一化导致的未触碰no-op问题，浏览器未验收。

textarea初始CRLF/CR no-op已有效RED `/tmp/word-alt-ui-cr-red.log`，最小修复比较赋值后的DOM初值、未改时返回原raw pair，最终UI5项GREEN `/tmp/word-alt-ui-cr-green.log`，不把HTML规范化当作用户编辑；生产再次冻结。四来源实际inspect capability与标准XML预备夹具通过，built仍未运行。


最终真实built验收：root冻结统一dist后，4269上session68376 exit0；`/tmp/word-table-alt-built.log`最终`ok=true`、`errors=[]`。四来源恰好四次有意义保存：missing-props→修订2、paired-whitespace-title→11、merged-description→21、rtl-floating-clear→31。完整manifest `/tmp/word-table-alt-built-manifest.json`（同内容`/tmp/word-table-alt-built-evidence.json`），实际下载DOCX、四份result、四份重开HTML/PNG在`/tmp/docx-alt-text-built-VA6zov/`；浏览器Chromium140.0.7339.16，121个实际加载JS全部HTTP200且SHA匹配冻结本地dist（含main、engine、parse-worker）。四份下载SHA另行读盘复核通过，无重复成功保存。

每来源验证真实属性导航、原raw no-op（含CRLF/CR textarea显示归一但不创建草稿）、真实table handle裸NodeSelection禁用Alt入口、编辑/Undo/Redo属性值回读、刷新草稿、严格单个完整值对setTableAltText、真实Python patch与HTTP下载SHA、新修订明确重开及geometry/CSS/正文一致。ZIP/lxml与项目source回读确认只改直属两标签（缺tblPr仅允许必需空壳归一），隐藏continuation/all cell XML/非document ZIP部件不变，中文/XML符号/LF与literal字符引用不串义，RTL/浮动清空无其它变动。固定源HEAD实际核对为f8c17004fb730df11f0f743164ffd8b4281bb38c。

两轮保存前探针失败均保留：`/tmp/word-table-alt-built-probe-red.log`、`/tmp/docx-alt-text-built-8LDWdp/failure.{html,png}`是误点pending的table-select-all；修正为现有真实table handle。`/tmp/word-table-alt-built-focus-red.log`、`/tmp/docx-alt-text-built-1m3FfW/failure.{html,png}`是Undo后属性回读取消将焦点恢复到外部按钮，Redo未进入编辑器；探针增加真实点击cell与contains(activeElement)断言后通过。两轮均0保存，未改产品、未放松产品断言。统一build/预算/contract日志由root保存在`/tmp/office-alt-print-statistics-{build,budget,contract}.log`。仅声明浏览器编辑/DOCX替代文字专项通过，不声明生产授权HTTP、完整ARIA、桌面Word/屏幕阅读器或PDF验收。
