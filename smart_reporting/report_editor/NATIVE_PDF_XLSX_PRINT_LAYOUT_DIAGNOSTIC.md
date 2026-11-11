# PDF→XLSX 两页来源打印为六页的只读诊断（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只读上一批真实浏览器下载 `/tmp/pdf-link-radio-decimal-xlsx-browser/{source.pdf,converted.xlsx,rendered.pdf}`、当前 IR 与 XLSX print/pageSetup 实现；未修改 slot、行排布、图片参考区、页面布局或打印缩放。此缺口尚未解决。

实际来源两页均为 600×800 pt，XLSX 两个 worksheet。实际 host 输出为 6 页：Page 1 worksheet 占前 5 页，Page 2 worksheet 占第 6 页。第一页正文后续出现在多张打印页，第 4 页只有标题跨页的尾段 `rt – café €`；因此不能把额外页简单归因于一张源图片。

## 可复读的具体原因

1. `planColumnSlots` 将正文左锚和 table 边界都变成 sheet 列；`emitTable` 把源 table 三列 178、180、175 pt 的完整宽度分别赋给 A/C/F。其间 B/D/E 仍用默认列宽，合并 `A5:B5`、`C5:E5` 没有扣除这些中间列。按现有 writer 同一换算规则，实际 A/C/F 为 177.75、180、174.75 pt，B/D/E 各 48 pt，A:F 总宽 676.5 pt；源 table 宽 534 pt，而 host A4 整页宽仅 595.30 pt。即使不计打印页边距，也已经需要横向分页。
2. 源左右两栏各 8 行文字，ink 宽约 213.54、220.68 pt，重建落在 B2/E4 的默认窄列，均启用 wrapText。`emitTextRow` 对每个 PDF block 新增一行，没有保留相同 y 的左右栏关系，也没有将正文 block 横跨相邻 slot 合并。两栏因此再次大量换行并在不同行上下堆叠，造成纵向分页；仅设置 paperSize 无法纠正这一重排。
3. 图片保留采用独立且标明“不代表原图文相对排版”的参考区。既有 `embedXlsxPageImages` 在可编辑正文之后为 800 pt 源页分配整页高的 15 pt 行槽：标签在 A14、显式行到 70，实际图片 anchor 为零基 row 42→50。它有意不是原图文同页布局，进一步扩张打印使用区。此策略本轮没有改变。
4. `rebuildXlsx` 目前仅在存在家具 header/footer 时附加 pageSetup；本 fixture `furnitureHf=[]`，实际 XLSX 没有 pageSetup。host 因而默认输出 A4（595.30×841.89 pt），并非来源 600×800 pt。当前 native model 支持 paperSize、orientation、firstPageNumber；没有通用 custom source paper dimensions/margins/print-area 表达。补充 source 纸张参数可以单独改善打印元数据，但不能修复前三项，也不能据此宣称 2→2 页保真。

原始 IR、源框和 sheet 模型证据 `/tmp/pdf-xlsx-print-currency/print-ir.json`。独立只读 `frontend/smoke/pdf-xlsx-print-layout-diagnostic.py` 复读实际来源、XLSX 的列宽/单元格/合并/图片 anchors/pageSetup 及 host 页数，不调用转换或渲染、不修改产物：

```bash
.venv/bin/python smart_reporting/report_editor/frontend/smoke/pdf-xlsx-print-layout-diagnostic.py SOURCE.pdf DOWNLOADED.xlsx HOST.pdf --output print-layout.json
```

## 后续边界

可靠修复需要一起处理 slot 区间宽分配、正文跨 slot/二维行排布、表格合并与图片参考区的打印策略，属于布局模型工作，不能作为一个 pageSetup 小修。当前没有使用经验页面常数、栅格化、缩小字号、全局 fitToPage 或裁切 print area 来隐藏内容。保留该诊断后，本轮转而修复可独立验证的货币小数精度与货币/百分数列宽，见 NATIVE_PDF_XLSX_CURRENCY_PRECISION_ACCEPTANCE.md。整体保真继续 false，已生成且身份可读取的实际文件仍可下载。

后续限定增量只消除第一项重复宽度 claim，见 NATIVE_PDF_XLSX_TABLE_SLOT_WIDTH_ACCEPTANCE.md。该增量保留 minimum 2 chars clamp、默认字体/MDW、正文二维排布与图片参考区边界；本诊断中的旧 676.5 pt 是旧 builder convention，不能直接充当 actual host 物理宽。旧实际 host 表头上边框各横向打印 tile 的可见段合计为 787.4350 pt；不以局部 claim 修正冒称打印页布局已解决。

2026-11-11 本批实际下载经单次 Calc 后，表头边框可见总跨度降至 629.1500 pt、首列降至 219.7700 pt，页数从 6 降至 4。实际 PDF SHA `946d6e4946cff42a67251afc8138974ed42c105e937e9b6d0706cd9a4fcfe810`。root 已目视全部四页，表格横向拆页、正文二维流和图片参考区问题仍在；源 2 页未还原。上述旧 6 页诊断保留为修复前证据，当前结果以 NATIVE_PDF_LABEL_REQUIRED_SLOTS_ACCEPTANCE.md 为准，完整打印保真仍为 false。
