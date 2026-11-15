# PDF→XLSX 表格跨槽重复宽度 claim 专项（2026-11-11）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮按只读打印诊断，仅消除 table grid column 横跨多个 sheet slot 时“首槽放完整列宽、夹槽再使用默认宽度”的重复 claim，不修改默认字体/MDW、全局宽度公式、二维正文排布或图片参考区。不执行 OCR，不承诺两页来源打印为两页。

## 限定算法与保留边界

生产仅改 `vendor/pdf2docx/src/rebuild-xlsx/rebuild.ts` 的 `emitTable` 宽度循环。每个 table grid column 仍使用现有 `slotOf` 和 effective `boundsOverride ?? tableBounds(block)`，在其覆盖的 `[startSlot, endSlot)` 内按左端、内部真实 slot、右端分配 source interval claim；逐槽与已有宽度取 max。源 cell、style、行高、值类型与 horizontal/vertical merge 的生成逻辑保持。

- continuation table 继续继承已有 run anchor bounds，保留原 header 去重和几何容差，不混用发生漂移的下一页原始边界。
- 重叠表在同一个全局 slot 上仍取 max；独立非表格数字已有更宽 claim 继续保留，因而不声称每个受影响表的最终总宽都精确等于 source。
- 未被任何 table 覆盖的 gap/body slot 继续保持旧默认宽度，没有全局 autofit。
- 当既有 slot 聚类把极窄 grid column 的首末折入同一个 slot，保留该列原有 fallback claim，不修改 merge 或假装已经区分该网格。
- 既有最小 2 chars clamp 与固定 7 px builder convention 均未修改。Calibri 11 未安装时 host 的 Normal 字体替代会改变最大数字宽度 MDW；此物理宽度缺口仍明确未解决。

当前固定来源 IR table column widths 为 178 / 180 / 175 pt，总和 533 pt（检测器外框宽 534 pt 是另一观测值，不将两者混同）。内部 slot 分配约为 1.578 / 176.422 / 90.596 / 17.884 / 71.520 / 175 pt；第一小槽仍受既有 2 chars clamp。序列化后按旧 builder convention 复读的 A:F 总宽由 676.5 降为 545.25 pt。这个值仅为同一 builder convention 的回读，绝不是实际 host 物理 pt 与来源保真证明。

## 专项与独立原生比较

新增 `bridge/xlsx-table-slot-width.test.ts` 五项都出现真实 RED，涵盖普通 grid/横向合并、continuation override、重叠表、max 数字/gap/折叠 tiny fallback、同源真实复杂 PDF。最小改动后 4 项通过；剩余项只是测试将 sparse gap 与 dense undefined 作 deepEqual 的区别，调整测试数组读取后仅重跑该项并通过。证据 `/tmp/pdf-xlsx-table-slot-width/{red,green,green-boundaries}.log`，没有重复已过 native 或完整专项。

新 source factory `frontend/smoke/pdf-xlsx-table-slot-width-source.py` 明确复用上一批 currency source，保证新旧实际文件比较同源；两次生成字节相同，来源 SHA-256 为 `db01c13b8865a262ae9ce0123a38201b0071782e815f5091d401b9b455c3f373`。原生 green XLSX SHA-256 为 `cbf8439b35614b30260a75e718daffbab6a2c63f90464d19e012aff3b4170fdc`。

独立 `pdf-xlsx-table-slot-width-verify.py` 先复验既有 rich/font/decimal/currency/percent/源图片契约，再要求 A:F 都有真实 slot claim；指定同源 baseline 时剥离 `<cols>` 后，逐 worksheet XML 必须字节完全相同，整个 styles.xml 及每个图片文件 bytes 必须完全相同。对保留的真实 pre-fix XLSX 明确失败于缺少内部列 claim，`independent-red.log`；对 green 与 red 的同源比较通过，`green/independent.json`。绘图 marker 会随列几何变化，未把相对图文位置列入已通过范围。

## 实际 host 比较方式

专属 browser 入口 `frontend/smoke/pdf-xlsx-table-slot-width-smoke.mjs` 设置 `table-slot-width` variant，旧分支保持；默认新目录 `/tmp/pdf-xlsx-table-slot-width-browser-20261111`。root 统一冻结构建后运行，设置 `PDF_XLSX_TABLE_SLOT_BASELINE_DIRECTORY=/tmp/pdf-measure-radio-currency-xlsx-browser` 可用上一批实际签发下载作同源 baseline。来源身份不相等时拒绝比较，不能用无关文件证明改善。

实际 host 验证不再由 7 px 列宽公式反算 physical pt：对每个含已知 table 外侧表头的打印 tile，量表头上边框的实际可见水平线段 union 长度，再合计；同页 Region/Revenue 的实际 x 起点差测完整首列跨度，同时记录页数。旧实际 baseline 只读测量为 6 页，上边框可见段合计 787.4350 pt、完整首列 262.6300 pt。这说明旧 builder convention 的 676.5 pt 本就不等于真实 host 物理宽。

本轮实际 browser `/tmp/pdf-label-required-slots-xlsx-browser/summary.json` 已通过；37 个实际 JS 与统一冻结资产匹配、来源未变、四类 errors 为空。实际下载 5924 bytes，SHA `ee7576b9fae8b895c071178c93c66802279e125d310f441e85c1a312bc7cdf8b`。对其仅一次 Calc（profile/output 均 /dev/shm），实际 PDF 87363 bytes，SHA `946d6e4946cff42a67251afc8138974ed42c105e937e9b6d0706cd9a4fcfe810`；`host-independent.json` 核验通过。

同源新旧 host 表头上边框可见段总长 787.4350→629.1500 pt，首列 262.6300→219.7700 pt，实际打印 6→4 页；数值、货币/百分数精度、混合样式/字体及剥 cols 后原 sheet 内容/styles/media 保持。root 已目视四页，表格仍横向拆页，正文二维布局和图片参考区仍存在差异。该相对改善不代表来源 physical pt、打印 2→2 或整体版式通过。`overallFidelityPassed=false`、`printLayoutFidelityPassed=false`、`defaultFontMdwFidelityPassed=false` 与 manualReview=true 保持；已生成且身份可读取的文件继续按现有机制签发下载。统一身份及边界见 NATIVE_PDF_LABEL_REQUIRED_SLOTS_ACCEPTANCE.md。
