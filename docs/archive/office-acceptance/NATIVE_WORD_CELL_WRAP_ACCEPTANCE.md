# Word 单元格自动换行验收

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；来源真实命令、72次保存回读及 renderer 边界见 `NATIVE_WORD_CELL_WRAP_INVESTIGATION.md`。下文保留各阶段记录，最终浏览器结果见末段。

协议 `setTableCellWrap` 仅接受来源 blockId/hash 和1至50个有序矩形 steps，每步严格 top/left/bottom/right/wrap。使用 source 直属 noWrap 语义，wrap=true 删除直属属性，false 写 canonical noWrap；不声称完整 Word 样式继承。逻辑合并 owner 对应全部物理 continuation，补丁不重建单元格、不改 tcFitText/列宽/隐藏正文。固定布局或超宽表格可能仍按可用宽度换行，属性保存不等价于保证视觉不换行。

独立 core/project3项及 bridge5项先RED后GREEN，日志 `/tmp/word-cell-wrap-core-green.log`、`/tmp/word-cell-wrap-bridge-final.log`。root接通capability、保护/hash/外层严格字段、同表批次互斥、collector/replay确定投影、局部XML保存与真实回读、非document部件保留。

Python初始RED因capability缺失 `/tmp/word-cell-wrap-python-red.log`；集成bundle `/tmp/word-cell-wrap-bridge-integrated-build.log` exit0后，新增7项GREEN `/tmp/word-cell-wrap-python-green.log`：目标属性/非目标表格与ZIP保留，隐藏续格与tcFitText保留，非法steps/hash/保护/重复操作拒绝。另新增逆序两表+段落插删+section布局专项1项GREEN `/tmp/word-cell-wrap-python-indices.log`，证明最终回读按实际输出索引定位。collector/replay及伪造字段/hash/同表冲突2项GREEN `/tmp/word-cell-wrap-operations-green.log`。UI、统一构建、浏览器保存下载重开仍待完成。

UI已冻结：属性页独立自动换行入口、caret/矩形/合并下部归一、mixed/no-op、Undo、裸table NodeSelection拒绝、stale document/anchor确认与旧命令互斥5项GREEN `/tmp/word-cell-wrap-ui-frozen.log`。旧投影14项GREEN `/tmp/word-cell-wrap-mutual-regression.log`。独立实际集成review `/tmp/cell-wrap-integration-review/` 两张合并表逆序修改+段落插删保留hidden/tcFitText及非目标XML/ZIP；迟到无效step输出不存在。尚待统一构建与真实浏览器。

最终统一构建 `/tmp/office-wrap-error-navigation-build.log` exit0（完整types/Vite40.28s），同前缀budget/contract均exit0，Word main161.3KiB；新增错误检查导致的XLSX超预算通过模块分块修正，未抬cap。Word四来源built已放行，结果仍待验收。

## 最终 built 结果

2026-11-10，session84144 exit0，`/tmp/word-cell-wrap-built.log`四来源4/4通过，恰好四次保存，无重复来源：auto caret revision2、fixed mixed矩形revision11、RTL矩形revision21、merged owner下部真实caret revision31。每次都执行noop/mixed、UndoRedo、草稿刷新、Python patch、HTTP下载SHA、ZIP仅直属noWrap变化与明确保存修订重开；live/draft/reopened geometry/CSS/正文一致。物理noWrap最终分别为[true,false,false,false]、[false,false,false,false]、[true,true,false,false]、[false,false,false,false]。merged隐藏continuation、tcFitText、未知节点及非目标ZIP bytes保持。root目视auto及merged重开截图，merged下部点击只证明同owner真实caret，不冒称UI独立logical lower slot。

总manifest `/tmp/word-cell-wrap-built-manifest.json`，全部产物 `/tmp/docx-cell-wrap-built-X2U2pO`；Chromium140.0.7339.16，121个实际加载JS全部HTTP200且与本地dist SHA一致，console/pageerror=[]。docx-main SHA ddcd80cb77eeff4b6fb150868cf857d5f550f7a7e828521a956577cec192165f；engine SHA 5da009cd517635838dd7c91210647148af3cf61d73c83fba18af5f96d4fd0612。各下载完整SHA与实际资源身份见manifest。授权/修订路由为本地夹具；不宣称生产鉴权、桌面Word/PDF或完整样式继承等价。
