# 透视表来源工作表删除依赖检查

固定来源：`/home/junge/pros/genoffice-source-full`，ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 缺口与来源依据

`packages/xlsx-gateway/src/gateway/xlsx-gateway.ts:1953` 收集 `^xl/pivotCache/pivotCacheDefinition[^/]*\.xml$`；2053–2065 行在删除来源工作表前调用 `pivotCacheReadsFromSheet`，拒绝仍有透视表读取该工作表的删除计划。`xlsx-sheets.ts:574` 检查 `worksheetSource@sheet`，解码属性并忽略工作表名大小写。

本地 `sheet-ops.ts` 原先只检查存续工作表公式、图表和定义名称等依赖，未读透视缓存来源。仅检查被删工作表是否承载透视表不能发现存续工作表上的透视表读取被删工作表这一情形。

## 最小实现与公开接口

`pivot-cache-source.ts` 提供纯函数 `isPivotCacheDefinitionPath(path)` 和 `pivotCacheReadsFromSheet(xml, sheetName)`，从引擎公开入口及现有通配子路径导出。独立模块只依赖既有 Saxes，不引入 ZIP 模块。`applySheetEdits` 在组装/修改 ZIP 前扫描缓存来源；命中时拒绝整个删除计划。无关删除保留原有透视表与缓存来源。

属性解码与大小写语义沿用固定来源；命名空间处理是明确的本地兼容改进：按 SpreadsheetML transitional/strict URI 识别元素，仅接受无命名空间的 `sheet` 属性，支持默认/任意前缀/局部绑定和单引号。忽略外来同名节点、注释及外来属性；不重复解码实体。完整 XML 解析失败或含 DOCTYPE 时拒绝预检，避免未读取完整来源却报告安全。固定来源使用无前缀正则，本地没有照搬这个前缀限制。

透视缓存来源改名的后续补齐见 `PIVOT_SOURCE_SHEET_RENAME.md`。本删除检查不扩展行列编辑、命名范围/表名来源解析或透视表承载工作表的级联删除支持；与固定来源一样，所有匹配路径的缓存定义均保守纳入检查。

## 验证证据

`packages/xlsx-engine/tests/pivot-source-sheet-removal.test.ts` 用 openpyxl 生成实际 XLSX ZIP，含来源工作表、存活透视表、缓存、所有关系和独立无关工作表。默认命名空间、别名前缀及带实体/大小写变化的来源三个删除用例先 RED（原实现返回 XLSX 而未拒绝）；无关删除原本通过。原始失败日志：`/tmp/pivot-source-engine-red.log`。

最小实现后新 13 用例与既有 sheet-ops 19 用例通过：`/tmp/pivot-source-engine-green.log`。拆分纯 helper 后重跑新用例 13/13：`/tmp/pivot-source-engine-final-green.log`；引擎严格类型检查通过：`/tmp/pivot-source-engine-final-types.log`。helper 边界覆盖数字/命名实体、单次解码、命名空间局部重绑定、外来属性/节点、注释、strict URI、损坏 XML/DOCTYPE 及固定来源路径范围。

未运行全量测试，未自行构建/打包，未改前端；前端原子预检、统一 build 和浏览器验证由 root 完成。
