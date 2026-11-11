# 原生 XLSX 图表插入验收

调查/实现日期：2026-11-11。固定源：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 已接入

- Insert ribbon 的 column、bar、line、area、pie、scatter、radar、doughnut、combo 命令进入 `workbook-main.ts`。
- 选区值沿用 xlsx-engine `chartDataFromValues` 识别表头、分类和序列；生成引用范围、内联缓存值及右侧绘图锚点。
- 草稿 operation 使用 `applyChartAdditions`，回放时调用现有 `chart-add.ts` writer；保存时由 `native_office.py` 和 `delivery/xlsx.py` 白名单放行。
- `readWorkbook` 重开可解析 chart part、类型、标题、系列和锚点。没有新增 Plotly 或新增图表 writer。
- Chart Design ribbon 接入标题、图表类型、图例位置、分类轴/数值轴标题、数据标签以及分组/主网格线格式编辑；只使用 `readWorkbook` 从当前 sheet 解析出的 `chartPath`，以 `applyChartEdits` operation 写回并经过相同草稿/保存/重开链路。

## 定向验收

`frontend/src/workbook-chart-add.test.ts` 覆盖：

- 列方向柱形图：选区值/类别映射到对应单元格公式引用，写入 XLSX 后重读仍有图表和系列引用。
- 行方向条形图：类别/值引用按行映射，工作表名含撇号时正确转义。
- 编辑 trusted chartPath 的标题、类型和图例，写入 XLSX 后重读确认标题与类型。
- Chart Design 弹窗编辑分类轴标题、数据标签，写入 XLSX 后回读 chart XML 确认轴标题和 `showVal`。
- Chart Design 编辑柱形图分组和主网格线，写入 XLSX 后回读 `c:grouping` 与 `c:majorGridlines`。
- Chart Design「选择数据」使用当前选区替换单图系列，写入新 `seriesSet` 引用和缓存；组合图明确拒绝。
- 修正非 A 列选区的引用列偏移，创建和“选择数据”现在均按实际选区起始列生成 OOXML 引用。

已运行：

- `frontend`: `vitest run src/workbook-chart-add.test.ts`，2 passed。
- `frontend`: 更新后 `vitest run src/workbook-chart-add.test.ts`，3 passed。
- `frontend`: `vitest run src/workbook-chart-design-dialog.test.ts src/workbook-main-sparklines.test.ts -t 'chart|Chart|format|edits chart axis'`，5 passed（4 skipped）。
- `frontend`: `vitest run src/workbook-main-sparklines.test.ts -t 'edits chart axis'`，1 passed。
- `workbook_engine`: `vitest run packages/xlsx-engine/tests/chart-add.test.ts`，6 passed。
- `workbook_engine`: `vitest run packages/xlsx-engine/tests/chart-edit.test.ts packages/xlsx-engine/tests/chart-read.test.ts`，20 passed。
- `workbook_engine`: `npm run typecheck`，passed。
- `reporting/tests/test_workbook_engine_bridge.py -k 'static_image or workbook_images'`，7 passed。
- `frontend`: `vitest run src/workbook-ribbon.test.ts` 有 1 个既存失败：`slicer-open` 预期启用；该失败与图表改动无关，文件含其他未提交工作区改动。

## 限制

- 选择暂以活动工作表唯一已解析图表为目标；尚无画布图表 hit-selection。Chart Design 可编辑 title/type/legend/轴标题/数据标签/分组/网格线/选择数据；推荐图表仍未接入，完整格式面板也未完成。
- 切换行列已接通同表带文字表头、分类标签和有限数值的连续矩形来源（最多 32 个系列、32 个分类）。支持柱/条/线/面积图，拒绝组合图、外部/跨表、名称、字面数据、非连续引用和表头身份不一致。复用 `seriesSet`，会重建系列；系列级自定义样式、趋势线等扩展不承诺保留。尚未完成真实浏览器和桌面 Excel 验收，也未实现原生 Undo/Redo。
- `workbook-chart-switch.test.ts` 验证切换与切回、撇号表名及不支持来源拒绝；主集成测试验证无关活动选区不影响图表来源、未保存数值保留，以及两次切换后的文件引用回读。
- 推荐图表入口仍禁用；创建需先选定数据范围。
- 图表 operation 可随当前工作簿草稿保存为新修订；用户需在下载文件或 Excel 中查看最终图表外观。
