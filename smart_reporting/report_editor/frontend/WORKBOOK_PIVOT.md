# 工作簿数据透视表创建与编辑

固定移植源：/home/junge/pros/genoffice-source-full，提交 f8c17004fb730df11f0f743164ffd8b4281bb38c。
参考 apps/sheets/src/renderer/pivot-actions.ts、PivotDialog.tsx、PivotFieldPane.tsx、pivot-field-model.ts；计算与OOXML写回复用项目现有 xlsx-engine/pivot-layout、pivot-add、pivot-expand，不另造透视表计算器。

## 已接入

- “插入 / 表格”与“数据 / 数据透视表”均有中文创建、编辑入口，使用已有SVG图标。
- 来源可选工作表+区域，或选择已存在Excel表解析当前区域（排除合计行）。固定来源区域，不承诺来源表后续扩张自动跟踪；可再次编辑区域。
- 来源首行必须非空、唯一字段；至少一行数据；最多10000数据行、200列。
- 行和列字段可增删、上下移动排序；至少一个行字段。值字段支持求和、计数、平均值、最大值、最小值，最多8项。
- 固定源和现有引擎共同限制：设置列字段时只支持1个值字段；不设置列字段时支持多个值字段。界面和提交校验均明确提示。
- 支持引擎已有的占总计、占行总计、占列总计百分比，以及可落入dataField.numFmtId的内置数字格式。任意自定义数字格式不静默降级。
- 可选目标工作表与单元格。编辑现有透视表固定原名称、目标工作表与起点，保留table/cache身份和关系；来源与字段可重配。
- 真正创建pivotTableDefinition、pivotCacheDefinition、pivotCacheRecords及表内输出，不以普通静态汇总冒充透视表。
- 普通Excel OOXML无项目私有状态扩展时也可读取基本字段并编辑；使用既有rebuildPivotOutput同时重建缓存记录、可见输出、清理旧输出尾部。
- 来源/输出冲突、已有占位、重复名称、非法字段、损坏关系均在完整当前草稿字节预演中失败，确定前不提交。取消不更改草稿。
- 提交仍写同一个NativeDraft，保留手工改动，与既有原生保存/下载/新修订机制共用；功能区撤销恢复和Ctrl/Cmd+Z、Ctrl+Y、Cmd/Ctrl+Shift+Z在网格无后续修改时使用原生草稿历史。后续网格修改优先走网格历史。
- 完整文件替换前仍遵守selectionListener dispose → load → subscribe，防止旧Workbook选择监听访问已释放unit。

## 明确未接入

报告筛选、项目/值筛选、共享缓存多透视表的安全重排仍未接入。本地已有“插入 / 筛选器”下的切片器与时间线会话入口：它们选择现有透视表的行/列字段，保存成员隐藏状态并重建透视输出；入口不是工作表上的原生控件。不会生成或更新 `xl/slicers`、`xl/slicerCaches`、`xl/timelines`、`xl/timelineCaches` 等 OOXML 部件。含这些原生控件的工作簿拒绝该入口的筛选编辑，避免控件状态与透视缓存失去同步。来源新增日期后，时间线需重新选择区间。未支持的导入显示方式/格式亦提示不可编辑。没有宣称与固定源整个透视表功能集完全等价。

## 验证入口

- frontend: npx vitest run src/workbook-pivot.test.ts src/workbook-pivot-dialog.test.ts src/workbook-native.test.ts
- xlsx-engine: vitest run tests/pivot-expand.test.ts tests/pivot-add.test.ts tests/pivot-refresh.test.ts
- 真实浏览器：统一构建前端与workbook engine bundle后，在frontend目录运行：
  WORKBOOK_EXPECTED_MANIFEST_SHA256=<本次manifest的sha256> WORKBOOK_SMOKE_EVIDENCE_DIR=/tmp/workbook-pivot-verified node smoke/workbook-pivot-gui-smoke.mjs
- 浏览器用例使用真实Chromium、预览已构建静态资源、真实native_office引擎补丁；HTTP身份/保存路由为确定性夹具，不冒充生产权限端到端验证。
- 用例覆盖跨工作表创建、多行轴/列轴、编辑改成多值五聚合、取消、原生撤销恢复、刷新恢复草稿、保存下载、修订2重开、严格pageErrors=[]。
- 下载文件独立ZIP+openpyxl回读table/cache/records、聚合类型、记录数量与可见总平均25；保存manifest/runtime JS SHA、原文件/下载文件/截图/evidence.json，失败保留failure.json/截图，不过滤错误。

本文件不包含发布验收通过声明；每次真实浏览器结果以对应evidence.json的ok、pageErrors和构建身份为准。


## 2026-11-11 最终构建验收

- 主代理统一构建、budget、contract 均exit0；本次未自行构建或调整预算。透视表helper/dialog使用动态导入，构建为独立workbook-pivot chunk。
- 冻结manifest SHA256：e13de64ff923e7fb122a0e0b053331d7de3729247c7526f1f32d859c3868b210。
- 真实浏览器实际加载：/reports/v1/editor/assets/assets/lazy-workbook-pivot-B6gt8Vim.js，12852字节，SHA256 8df71966afc30da06177a89ba565783cc0fa09928800903930f628c2ccb66c0a。
- 浏览器Chromium 157.0.8103.38，production preview=true，ok=true，严格pageErrors=[]。
- 创建：数据!A1:E5 → 分析!B2，多层行字段区域/团队、列字段年份、收入求和。编辑：区域行字段、4值字段average/count/max/min。原生撤销恢复、取消、刷新恢复草稿、真实保存下载、修订2重开并读回字段全部通过；手工A1加粗保留。
- 独立ZIP/openpyxl回读：实际pivotTableDefinition、cacheDefinition、cacheRecords存在；记录4条；同一name/cacheId保留；最终区域B2:F5；总平均25；旧输出尾部已空。
- 下载文件SHA256：ddbb8e978c34dd45e00a5e5942f6e9485f6549e5283096e5237a9460e9e352a2。
- 完整证据：/tmp/workbook-pivot-built-final-20261111/{source.xlsx,saved.xlsx,downloaded.xlsx,reopened-dialog.png,evidence.json}；运行日志/tmp/workbook-pivot-built-final-20261111.log。已实际查看截图：中文来源与字段控件、聚合值可读；长配置通过对话框内部滚动访问目标与确定/取消。
- 本次HTTP身份与保存端点是确定性夹具，真实保存调用native_office及workbook engine；不声明生产身份授权或AI provider验收。

### 失败历史与实际修复

- /tmp/workbook-pivot-dev、/tmp/workbook-pivot-dev2 保留早期失败截图与JSON。首轮恢复按钮断言在文件替换尚持交互锁时抢先检查；现有测试等待按钮可用，并把新透视表apply/history的功能区刷新放到锁释放finally后。开发模式的既存zoom-launcher嵌套button React告警如实记录，未过滤。
- 首轮生产构建/tmp/workbook-pivot-preview1完整走到保存下载，pageErrors=[]，但独立openpyxl发现目标工作表新增r:id未声明xmlns:r。已修复appendWorksheetPivotPart，增加无xmlns:r来源回归；最终引擎bundle包含该修复。
- 更早独立openpyxl文件探针发现引擎平均值subtotal=avg不符合标准枚举。修为average，旧avg仍可读；未用自家reader成功替代独立验证。
- 普通Excel无私有扩展的重排原路径只写定义、清空缓存且无法清除旧输出尾部；已复用既有rebuildPivotOutput完成真实记录/可见输出重建并删除本次产生的不可达旧清空路径。
- 定向验证：按需拆包后原生+透视表13/13、新增关系前缀回归1/1；既有ribbon44/44；engine add/expand/refresh20/20；前端及engine类型检查通过。没有重复运行完整测试套件。


## 最终构建final2：仅入口资产补验

PDF专属修复后主代理再次统一构建。工作簿生产源码与bridge未改；没有重复完整创建、编辑、保存、下载、回读或重开流程。完整透视表交互验收仍对应前述e13de64f…构建，不将其改记为新构建实测。

- final2 manifest：e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa。
- 入口专用命令：WORKBOOK_PIVOT_ENTRY_ONLY=1，配合WORKBOOK_EXPECTED_MANIFEST_SHA256与WORKBOOK_EXPECTED_PIVOT_JS_SHA256；沿既有native → workbook入口加载。
- 浏览器实际按需请求 /reports/v1/editor/assets/assets/lazy-workbook-pivot-B6gt8Vim.js，12852字节，SHA256 8df71966afc30da06177a89ba565783cc0fa09928800903930f628c2ccb66c0a，与e13完整验收时原始字节一致。
- 中文“数据透视表”“编辑数据透视表”按钮各含一个真实SVG。只打开配置对话框后取消，未提交透视表。
- 实际请求事件观测mutationRequests=[]，saveRequests=0，exportRequests=0；草稿operations=[]；严格pageErrors=[]；entryOnly=true、fullInteractionsNotRepeated=true、ok=true。
- 证据：/tmp/workbook-pivot-entry-final2-20261111-observed/{source.xlsx,entry-dialog.png,evidence.json}；日志/tmp/workbook-pivot-entry-final2-20261111-observed.log。首轮同范围补验/tmp/workbook-pivot-entry-final2-20261111也保留，后一次仅将零写请求断言绑定真实request事件，没有运行完整交互。
- 已实际查看final2入口截图，中文来源、行列值字段、目标、取消与确定均正常可见。未改生产代码、未构建、未更改预算，也未更新root中央scope/provider文档。
