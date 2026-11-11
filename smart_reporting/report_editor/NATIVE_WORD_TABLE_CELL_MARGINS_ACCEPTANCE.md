# Word 默认单元格边距验收

2026-11-10。本项最终浏览器验收已通过；全量 Word/XLSX 对齐仍开放。固定来源与九个真实源保存向量见 `NATIVE_WORD_TABLE_CELL_MARGINS_INVESTIGATION.md`。

本项对应 Ribbon 的整表默认边距，修改直属 `tblPr/tblCellMar`。所有单格显式 `tcMar`、样式/行例外、合并续格隐藏内容及其他 XML 保留。Cell 属性页的单格覆盖/恢复继承是独立缺口，不计作本项交付。

`setTableCellMargins` 绑定来源 block/hash，只接受 top/right/bottom/left 四个整数 twip，范围 0–28350；0 是显式零。可信 capability 同时记录有效默认、各 owner 的有效覆盖和显式 raw 默认声明。前端只投影默认值及其编辑标记，collector、草稿回放、同表混编守卫、Python 白名单与真实保存回读一起接入。独立页面设置不被无依据拒绝。

UI 显示精确 pt，支持显式长度单位。未编辑字段直接保留来源整数，直接确认不派发事务，避免源二位小数 cm 中间态带来的无操作量化。普通光标、矩形和整表选择都定位同一张表，并核验对话框打开后的文档、选区和来源身份。

## 已核验

- core/project/旧投影互斥 5 项，bridge 6 项通过；覆盖真实样式/行例外/部分覆盖/RTL/纵合并隐藏内容、缺容器/自闭合容器、零值、start/end 与单引号、未知 sibling 保留和歧义来源拒绝。日志 `/tmp/cell-margins-core-project-final-green.log`、`/tmp/cell-margins-bridge-final-green.log`。生产范围 types exit0。
- UI 5 项通过（初轮 3 项及修正越界测试后窄重跑 2 项），types exit0。输入采用来源 twip 舍入契约，1417.51pt 舍入后未越界；真实越界使用1417.6pt。日志 `/tmp/word-cell-margins-ui-green.log`、`/tmp/word-cell-margins-ui-input-green.log`、`/tmp/word-cell-margins-ui-types.log`。
- Python `/tmp/word-cell-margins-python-green.log` 6 项通过：各物理单格 XML 全文保持、奇数 twip/显式零、非法输入、hash/保护、独立页面设置。首 `/tmp/word-cell-margins-python-red.log` 确认缺 capability 后才接入。
- 最终 bridge `/tmp/word-cell-margins-final-bridge-build.log` exit0。统一前端与四来源浏览器验证均通过；未重复完整测试。

授权/修订替身不能证明生产 HTTP、桌面 Word 或 PDF 排版完全等价。

最终统一前端 `/tmp/office-margins-hidden-final-build.log` exit0（40.01s），budget与contract exit0。新增长度解析调用使render略超预算，精确拆出 `lengths.ts` 后render709.9KiB、Wordmain160.5KiB，未提高cap。

四来源实际浏览器首轮 `/tmp/word-cell-margins-built-smoke.log` exit0、`ok=true/errors=[]`，产物 `/tmp/docx-cell-margins-built-jQTQuL/`。普通、横纵合并、bidiVisual、竖排分别保存为修订2/11/21/31，四次均只提交 `setTableCellMargins`，值 `{top:0,right:176,bottom:96,left:130}`。无操作确认精确保持109twip的5.45pt及DOM；UndoRedo、草稿刷新、真实Python patch、HTTP下载SHA、ZIP回读与明确新修订重开均通过。所有物理cell XML全文、仅mask直属tblCellMar后的document.xml及其他parts身份保持，`cellOverridesPreserved=true`、`onlyTableDefaultsChanged=true`；121个加载chunk的HTTP200/SHA检查通过。

真实布局证据：普通默认格左padding从7.2px变为8.667px、右padding从7.267px变为11.733px；显式left33的owner保持2.2px。merged owner高度从208.09375px变为219.96875px，竖排首格内容左偏移从71.109375px变为86.421875px；四来源重开geometry与修改后精确一致。UI agent已目视修订11和31的重开截图，合并结构、竖排及中英文/emoji内容保留。该浏览器证据使用授权/修订路由替身，不扩大为生产HTTP、桌面Word或PDF等价结论。
