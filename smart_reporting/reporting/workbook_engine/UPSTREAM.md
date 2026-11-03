# Upstream 来源登记

vendored 代码统一来源：genoffice @ `f5247d3`（本地路径 `/home/junge/pros/genoffice`）。
移植方式：**选择性移植 + 精简重写**（Mimosa 安全钩子要求源码经 Write/Edit 提交，整树 cp 被拦截；
由此改为按文件移植——小文件逐字移植，大文件按 web 所需裁剪重写，算法保持一致）。
回移上游补丁时按下表对位，并在本表追加变更记录。

本表登记来源与实现子集，不是全量对齐或浏览器验收证书。日期追加保留迁移历史；当前边界以 [alignment-matrix.md](docs/alignment-matrix.md) 和 [implementation-plan.md](docs/implementation-plan.md) 的当前证据/验收清单为准。2026-10-01 主代理提供的 190 测试、typecheck 与生产构建通过仅为并发 pivot/CF 修改前的历史快照。**2026-10-01 最终验证**：typecheck（4 workspace）+ 256/256 测试（i18n 5、engine 153、AI 16、web 82，含保存取消诚实状态与 NaN 拒写回归）+ 生产构建通过（gate 退出码 0）；pivot 引擎路径（创建烘焙矩阵、刷新 append-only + 重烘焙、扩展/relayout + 收缩清单元格）与图表创建（xlsx-drawing-add chart 分支移植 + addCharts AI 操作）由单测验证；浏览器验收覆盖凭据边界、批准/拒绝、值/样式写入与撤销、包级撤销、保存状态，以及透视表创建/刷新/扩展（烘焙矩阵入网格）与图表创建管线；磁盘落盘与 Excel 互操作仍未验证。根 `npm run gate` 仅执行 typecheck + Vitest，不含 Playwright。

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `packages/xlsx-engine/src/cell-address.ts` | `xlsx-gateway/src/domain/cell-address.ts` | 逐字移植 | 正则改 `[$]?` 写法、`str.match` 代替 `.exec`（安全扫描约定） |
| `packages/xlsx-engine/src/style-color.ts` | `domain/style-color.ts` | 逐字移植 | `.exec` → `.match` |
| `packages/xlsx-engine/src/short-date.ts` | `shared/short-date.ts` | 逐字移植 | |
| `packages/xlsx-engine/src/future-functions.ts` | `gateway/future-functions.ts` | 逐字移植 | |
| `packages/xlsx-engine/src/xlsx-escapes.ts` | `gateway/xlsx-escapes.ts` | 逐字移植 | |
| `packages/xlsx-engine/src/xml.ts` | `gateway/xlsx-gateway.ts`（文本辅助函数段）+ `gateway/xlsx-namespace.ts` | 摘取移植 | decode/escape/readAttribute/sectionInner + 命名空间归一化 |
| `packages/xlsx-engine/src/sha256.ts` | 新写 | 新增 | 纯 JS SHA-256 替代 node:crypto（同步签名、浏览器可用） |
| `packages/xlsx-engine/src/edit-schemas.ts` | `shared/edit-schemas.ts` | 裁剪移植 | 仅保留 rich-run / 颜色 / 填充 / 边框 / workbookStyleEdit |
| `packages/xlsx-engine/src/style-read.ts` | `gateway/xlsx-style-read.ts` + 扩展 | 移植+扩展 | 增加 fonts/borders/alignment/numFmts/theme 调色板解析（web 无 sidecar） |
| `packages/xlsx-engine/src/styles-write.ts` | `gateway/xlsx-styles.ts` | 逐字移植 | StylesheetEditor COW；`.exec` → `.match` |
| `packages/xlsx-engine/src/zip.ts` | `gateway/xlsx-gateway.ts`（zip 段） | 摘取移植 | Uint8Array 化、纯 sha256、assemblePackage/assertOnlyTouchedEntriesChanged |
| `packages/xlsx-engine/src/workbook-read.ts` | `gateway/xlsx-gateway.ts`（读取段）+ `gateway/xlsx-sheets.ts` | 摘取+扩展 | 值/公式/样式索引 + 几何（行高列宽/合并/冻结/维度）读取 |
| `packages/xlsx-engine/src/workbook-write.ts` | `gateway/xlsx-gateway.ts`（写入段） | 摘取移植 | patchCell/serializeStyledCell/insertMissingCell/ensureFullCalcOnLoad + 值与样式编辑（结构/图表等桌面能力未迁） |
| `packages/xlsx-engine/src/blank.ts` | `gateway/csv-import.ts`（blankXlsxBuffer 思路） | 重写 | 最小合法 xlsx 生成器（Uint8Array） |
| `packages/ai/src/agent/{types,skill,loop,stream-text}.ts` | `agent-core/src/*` | 逐字移植 | electron-transport 未迁（web 用自建 transport） |
| `packages/ai/src/provider/{types,providers,registry,stream,chat,fetch,watchdog,network-error,overload-error,output-cap,http-error}.ts` | `ai-provider/src/*` | 裁剪移植 | 剔除 genspark(gsk)/codex/media/search；SSE 用 Web ReadableStream |
| `packages/ai/src/provider/protocols/*.ts` | `ai-provider/src/protocols/*` | 逐字移植 | anthropic / gemini / gemini-schema / openai-compatible / shared |
| `apps/web/src/grid/create-univer.ts` | `apps/sheets/src/renderer/create-univer.ts` | 移植 | preset 类型放宽（依赖树嵌套 core 的类型现实） |
| `apps/web/src/core/univer-data.ts` | `apps/sheets/src/renderer/univer-sync.ts`（loadSnapshotIntoUniver 数据形状） | 摘取+扩展 | 纯函数化（可测），样式经 workbook styles map 而非事后 facade |
| `apps/web/src/core/{style-map,session-core}.ts` | 新写（参考 univer-sync/edit-journal 思路） | 新增 | 逻辑样式中立层 / diff→CellEdits / AI 写入 schema+审批+撤销 |
| `apps/web/src/ai/skill.ts` | 参考 `renderer/ai/workbook-skill.ts` 设计 | 重写 | list/read/search/apply_edits + verifyResponse |
| `apps/web/src/ai/transport.ts` | 参考 `renderer/ai/transport.ts` + 主进程 aiStream handler | 重写 | BrowserAgentTransport 直调 streamForProvider |
| `apps/web/src/ai/settings.ts` | 新写 | 新增 | IndexedDB 仅持久化 provider/model/base URL 等元数据；浏览器不读取、接受或持久化 API 密钥，已认证 provider 在请求前阻断；仅允许无凭据自定义兼容端点，未来认证支持需获批准的环境或密钥服务边界 |

## 与上游的环境差异决策

- **Buffer → Uint8Array / 纯 JS sha256 / TextDecoder**：引擎无 node: 依赖（`grep -rn "node:" packages/` 为零）。
- **无 Rust sidecar**：浏览器 Worker 路径已实现；大文件靠 ZIP 上限 + 明确报错，内存/响应性与回退仍需浏览器验证。
- **npm 依赖矩阵**：全部 @univerjs 包钉精确 `0.25.1`（preset 的内部依赖为精确版本，`^` 区间会混装 0.25.1/0.25.2 产生双注入器——`[redi] Cannot find …` 启动崩溃）；vite 经 overrides 钉 `^7.3.6` 防与 vitest 的副本冲突。

## 2026-09-29 对齐追加（genoffice 能力差距收口）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/sheets-edit.ts` | `gateway/xlsx-sheets.ts` | 裁剪移植 | 重命名跨包引用改写/新增/删除 fail-closed；剔除 clone/duplicate 与 pivot-cache 改名；`.exec`→`.match` |
| `xlsx-engine/src/structural.ts` | `gateway/xlsx-structure.ts` + `domain/formula-shift.ts` | 摘取重写 | 插删行列：几何/公式（同表+跨表限定引用/definedNames/#REF! 收缩）/合并/维度；绘图、OLE/VML 锚点、范围特性及已支持的表格部件随动；当前仅对 pivotTable/pivotSelection 标记 fail-closed，未覆盖的扩展部件仍需单独验证 |
| `xlsx-engine/src/sheet-ops.ts` | `gateway/xlsx-gateway.ts` 的 applySheetPlanToPackage/结构编排 | 重写 | applySheetEdits / applyRowColumnOps 编排 + calcChain 处理 |
| `web style-map/sync` 边框扩展 | 桌面版边框往返语义 | 移植 | Univer BorderStyleTypes ↔ OOXML 线型名映射，四边双向 + diff 写回 |

## 2026-09-29 对齐追加（第三轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/csv.ts` | `gateway/csv-import.ts` 思路 | 重写 | RFC4180 解析 + 分隔符嗅探 + 类型化导入；导出为活动表 CSV（新增能力） |
| `structural.ts` 锚点/范围平移 | `xlsx-structure.ts` 的 shiftDrawingAnchors / moveAnchorMark / ranged-features 平移 | 摘取移植 | 线性插删语义（无 move-rows swap）；绘图、OLE/VML 锚点、范围特性及已支持的 tablePart 会随动；仅 pivotTable/pivotSelection 标记 fail-closed，未覆盖的扩展仍需单独验证 |
| `sheet-ops.ts` drawing 接线 | `xlsx-gateway.ts` 的 shiftAnchoredSheetParts | 摘取重写 | worksheet rels → drawing part 解析与平移 |

## 2026-09-29 对齐追加（第六轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/structural.ts` 表格段 | `xlsx-structure.ts` 的 shiftTablePart/reshape/insert/removeTableColumns/assertTableRowShiftSupported | 摘取移植 | 无 move-rows swap；插入点为「严格表内」语义 |
| `xlsx-engine/src/workbook-write.ts` setWorksheetCellText | `xlsx-gateway.ts` 的 writeHeaderCellText | 摘取移植 | 表头单元格文本回写（保留样式索引） |
| `xlsx-engine/src/rules.ts` | `xlsx-dv.ts` / `xlsx-cf.ts` 写入路径 | 精简重写 | DV 全类型/比较符/提示；CF `cellIs` / `colorScale` / `dataBar` / `iconSet` 与 COW DXF 有测试且随 2026-10-01 最终 gate 全绿；x14、完整规则族/导入/网格渲染仍缺（见 alignment matrix） |

## 2026-09-29 对齐追加（第七轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/chart-edit.ts` | `xlsx-chart.ts` 全量写路径（applyChartEdit 及全部 set* 操作） | 全量移植 | 标题/类型互转/系列色 + 图例/数据标签（模式+位置+格式）/轴标题（含 dateAx 回退）/堆叠（overlap 联动）/网格线/值轴界（CT_Scaling 顺序）/间距/孔径/饼图爆炸（整体+逐片 dPt）/点色/整组换系列（seriesSet，散点重建）/单系列改写（引用不降级、数值分类保留 formatCode）；`.exec`→`.match`；16 项引擎测试 |
| `xlsx-engine/src/chart-add.ts` | `gateway/xlsx-drawing-add.ts`（chart 分支） | 移植 | 创建 chart/drawing 部件 + 关系 + [Content_Types] + 锚点（twoCellAnchor 归一化、多图复用 drawing、未触碰条目字节不变断言）；MutablePackage → EntrySource+overlay+assemblePackage；sheet 名经 workbook.xml 关系解析为部件路径；`.exec`→`.match`；上游 shape/image 分支未移植（无对应 AI 操作） |
| `apps/web/src/core/chart-add-plan.ts` | 桌面 `visual-actions` 的 chartDataFromValues→ChartAdd 组装 + `ai/prompts/guides/charts` 的 add_chart 入参形态 | 摘取重写 | addCharts AI 操作：chartDataFromValues 提取系列（转置双向绝对引用链接源数据）、写后即图同载荷合并（applyValueEditsToReadback）、默认锚点在数据区右侧；单测覆盖双向引用/单系列默认标题/拒绝无系列与未知表 |
| `xlsx-engine/src/rules.ts` 图表编排 | `xlsx-gateway.ts` 的 chart edits 接线 | 重写 | listChartParts 发现 + 按路径 applyChartEdits |

## 2026-09-29 对齐追加（第九轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/notes.ts` | `gateway/xlsx-notes.ts` | 逐字移植 | ensureRelationshipNamespace 移入 xml.ts 并导出；适配 MutationPlan 编排 |

## 2026-09-29 对齐追加（第十轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/pivot-add.ts` | `gateway/xlsx-pivot-add.ts` | 精简移植并持续扩展 | 引擎/OOXML 路径实现多级行/列轴、分组、计算字段、筛选、showDataAs、缓存预填充，并通过 `computePivot`/`rebuildPivotOutput` 把计算矩阵烘焙进工作表单元格（含收缩时清除旧输出）；pivot 引擎测试 27 项全绿（2026-10-01）；浏览器端仍是 OOXML/package writer，不等于完整透视表渲染或布局编辑；私有分组 extLst 与真实 fieldGroup/rangePr 持久化仍是共同 TODO |

## 2026-10-01 对齐追加（第十三轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `packages/i18n/src/index.ts` | `packages/i18n/src/index.ts` | 精简移植 | 去掉 Electron 平台快捷键改写与进程级语言持有；保留 Lang/normalizeLang/htmlLang/format/defineStrings/createI18n |
| `apps/web/src/i18n/app/*.ts`（20 分片） | `apps/sheets/src/renderer/i18n/app/*` 结构 | 重写 | 48 键 web UI 文案；zh 定义键集 + defineStrings 编译期校验 |
| `apps/web/src/i18n/locale.tsx` | `apps/sheets/src/renderer/i18n/locale.tsx` 思路 | 重写 | React Context + localStorage + navigator.language 回退 |
| `xlsx-engine/src/pivot-grouping.ts` | `domain/pivot-grouping.ts` | 逐字移植 | `.exec`→`.match`；日期/区间分组 + isValidGrouping |
| `xlsx-engine/src/pivot-refresh.ts` | `domain/pivot-engine.ts` growPivotDefinition 语义 + `gateway/xlsx-pivot.ts` refreshOnLoad | 摘取重写 | 文件级刷新：append-only 追加 sharedItems（退役成员保留索引）+ 重建 records + `rebuildPivotOutput` 重烘焙工作表输出（含 pivotField items/rowItems 同步重建，布局跳过无记录成员）；分组规则从 pivotTable ext 读回；不再写 refreshOnLoad（包自洽） |
| `xlsx-engine/src/pivot-add.ts` groupings/extLst | `gateway/xlsx-pivot-add.ts` buildGroupingExtLst + 记录分组映射 | 摘取移植 | `{AIO-PIVOT-GROUPINGS}` 私有扩展；`{AIO-PIVOT-GROUPINGS}` 字面量与 genoffice 一致 |
| `xlsx-engine/src/pivot-source.ts` | `gateway/xlsx-pivot-add.ts` 读源辅助 | 抽取共享 | extractCellValue/readSharedStrings/readSourceAreaRows 内部模块（不进公共 API） |
| `apps/web/src/grid/sync.ts` openFindReplace | —— | 重写 | 弃合成键盘事件，改执行 find-replace preset 的 open-find/replace-dialog 操作 |

## 2026-10-01 对齐追加（第十四轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/pivot-formula.ts` | `domain/pivot-formula.ts` | 逐字移植 | `.exec`→`.match`；`replaceAll` 替换正则转义 |
| `xlsx-engine/src/pivot-filters.ts` | `domain/pivot-filters.ts` | 逐字移植 | 标签/值筛选匹配与校验 |
| `xlsx-engine/src/pivot-add.ts`（filters/hidden/calc/showDataAs） | `gateway/xlsx-pivot-add.ts` 的 buildFiltersXml/axisPivotField/计算字段写入 | 摘取移植 | `<filters>` 块、`h="1"`、cacheField@formula、dataField fld 追加索引、sum subtotal 隐式 |
| `xlsx-engine/src/pivot-refresh.ts` | —— | 适配 | parseCacheFields 跳过 databaseField="0" |
| `apps/web/src/App.tsx` 筛选编排 | 桌面 pivot 重算引擎的「先聚合后筛选」语义 | 重写 | App 端按成员聚合计算隐藏项并剔除布局行 |

## 2026-10-01 对齐追加（第十五轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `docs/alignment-matrix.md` | —— | 新增 | domain 17 模块 + gateway 28 模块 + AI 面逐项移植状态矩阵 |
| `xlsx-engine/src/pivot-expand.ts` | `gateway/xlsx-pivot-expand.ts` | 逐字移植 | MutablePackage → EntrySource/assemblePackage；`.exec`→`.match`；缩小 ref 取上游注释语义（静默跳过）；PivotAddition 形状适配（worksheetSheetName） |
| `xlsx-engine/src/pivot-add.ts` | 同上 | 导出 | buildPivotTableXml/buildCacheDefinitionXml 导出供 relayout（与 genoffice 导出理由一致） |
| `apps/web` expandPivots 操作 | —— | 新增 | AI 面：按名解析→增长，走审批/撤销链路 |

## 2026-10-01 对齐追加（第十六轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/protection.ts` | `gateway/xlsx-protection.ts` | 逐字移植 | `.exec`→`.match`；增加 protectSheet/protectWorkbookStructure 字节级编排 |
| `xlsx-engine/src/page-setup.ts` | `gateway/xlsx-page-setup.ts` | 逐字移植 | `.exec`→`.match`、`\$?(`→`[$]?` 约定；增加 applyPageSetups 批量编排（工作表 + workbook.xml 一次重写） |
| `apps/web` protectSheets/protectWorkbook/setPageSetups | —— | 新增 | AI 面，走审批/撤销链路 |

## 2026-10-01 对齐追加（第十七轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/sort-range.ts` | `domain/sort-range.ts` | 逐字移植 | CellState/CellScalar 换成本仓 SortCellState/SortScalar（自含类型，不依赖 workbook.types） |
| `xlsx-engine/src/flash-fill.ts` | `domain/flash-fill.ts` | 逐字移植 | 纯函数无适配 |
| `apps/web` sortRange/flashFill 操作 | —— | 新增 | planOps 值级路径（undo 逆写）；闪填源字段排除目标列（上游为 UI 选择列，无此问题） |

## 2026-10-01 对齐追加（第十八轮）

| 本仓库路径 | 上游来源 | 处置 | 备注 |
| --- | --- | --- | --- |
| `xlsx-engine/src/table-add.ts` | `gateway/xlsx-table-add.ts` | 逐字移植 | MutablePackage → EntrySource/assemblePackage；worksheetPath 改为按表名解析；`.exec`→`.match`、`[$]` 约定 |
| `xlsx-engine/src/theme.ts` | `gateway/xlsx-theme.ts` | 逐字移植 | `$1` 串替换改函数替换器（防 `$` 注入替换模式）；新增 setThemePart 字节级编排 + DEFAULT_THEME_COLORS |
| `apps/web` addTables/setTheme 操作 | —— | 新增 | AI 面，走审批/撤销链路；列名从表头行读取 |
