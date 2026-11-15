# 原生 XLSX 静态图表对齐调查

调查日期：2026-11-11。固定源：`/home/junge/pros/genoffice-source-full`，实读 HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 结论与交付边界

现有标准 Matplotlib 编译器与 XLSX 图片管线能完成静态图创建、图片身份核验、嵌入、同位置替换和真实 Excel 文件回读。纯 bytes 引擎也能消费服务端 PNG 的 base64 解码结果，不需要客户端文件路径。两条路径均已真实执行。

本轮仅补充调查与 `/tmp` 实证，不新增未接入口的生产 helper，不开启九类图表按钮。原生编辑器尚缺可信图表资产解析、选区冻结与元数据确认、图表候选/草稿持久化、预览和保存承接，不能宣称图表创建/编辑已对齐。

## 固定源事实

- `apps/sheets/src/renderer/ExcelShell.tsx:2544` 起提供 column/bar/line/area/pie/scatter/radar/doughnut/combo 九类按钮。
- `apps/sheets/src/renderer/visual-actions.ts:170` 的 `handleInsertChart` 读取选区；懒加载工作簿使用 `readChartGridValues` 从 sidecar 读取，避免仅使用未完整加载的网格；散点图显式使用首列为数值 X。
- 同函数构造 `WorkbookVisualObject`，含锚点、序列与源范围，进入 edit journal 的视觉对象变更。
- `packages/xlsx-gateway/src/gateway/xlsx-drawing-add.ts:181` 的 `applyVisualAdditions` 在 chart 分支实际分配 `xl/charts/chartN.xml`、调用 `buildChartXml` 并写 drawing relationship。这是原生 OOXML 图表。
- `packages/xlsx-gateway/src/gateway/xlsx-gateway.ts:1581` 读取已有 chart part，再通过 `applyChartEdit` 修改。`xlsx-chart.ts:196` 起可编辑类型/标题/系列等。

不能直接接入这套新建原生图表行为：项目要求新图只产出 Matplotlib PNG/JPEG；既有原生图表解析与保留兼容无需删除。

## 本地可复用能力

| 能力 | 真实入口 | 约束 |
| --- | --- | --- |
| 标准图源码编译 | `reporting/workflow/runtime/standard_visualization.py::standard_visualization_preflight` | 消费冻结、带 SHA256 的 `ChartInputMaterialization`；返回可信 Matplotlib 源码或结构化诊断 |
| 图族契约 | `standard_chart_contract.py::StandardChartForm` | 支持 bar/barh/line/stacked-area/pie/donut/scatter/radar 等；不等于九类 UI 无条件可映射 |
| 带身份图片操作 | `reporting/delivery/xlsx.py::patch_workbook` 的 `applyStaticImages` | Python 图片解码校验后，Node 使用前再次核对身份；坏图记录 issues |
| 图片拟合/溯源 | `workbook_engine/bridge/images.ts::applyStaticImages` | 按实际可见行列几何等比拟合，保留 `smart-reporting/source-mapping.json` |
| 纯字节 OOXML 嵌入 | `workbook_engine/packages/xlsx-engine/src/chart-add.ts:863` 的 `applyStaticImage` | 输入 `Uint8Array`、完整锚点和 PNG/JPEG MIME，不接受或解析 base64 字符串 |
| 原位替换 | 上述两个图片入口 | 带身份入口沿用 imageId/sheet/range；纯字节入口使用可信已存在 mediaPart 并匹配图片名及 relationship |

`bridge/images.ts` 能合并 snapshotId/chartRevisions、验证 sourceFiles、记录图片 SHA256/尺寸/sourceRanges；绝对宿主路径只用于读文件，导出身份使用 identityPath 或文件名。它会拒绝 imageId 改锚点。

`native_office.py::_XLSX_FIELDS` 未开放 `applyStaticImages`。`workbook_native_ai.py::_prepare_job` 也明确禁止图表和图片；`WorkbookDraft` 当前只是普通操作列表，不能据此视作已有可信图资产能力。不能仅把 applyStaticImages 加进白名单，让客户端任意传宿主 path。

## 真实探针

### 标准编译与完整现有图片桥

脚本 `/tmp/xlsx-static-chart-probe.py`，工作目录 `/tmp/xlsx-static-chart-probe`。使用真实生产模块编译及创建/修改 XLSX，openpyxl 仅独立回读：

1. 冻结 Period/Actual/Budget 三列和 Jan/Feb/Mar 三行数据，登记 Actual/Budget 单位为元。
2. `standard_visualization_preflight` 编译双系列 bar 图；在独立 Python 进程执行返回的服务器编译源码。
3. 生成 PNG 为 1800×1050；通过现有 `build_workbook` 建立数据工作表。
4. `patch_workbook(... applyStaticImages)` 将图片拟合嵌入 Data!E2:L18，登记源范围 Data!A1:C4、输入 JSON 身份和图片身份。
5. 同 imageId/sheet/range 以 chartRevision=2 原位替换。
6. openpyxl 回读确认图片数为 1，B2=10；独立 ZIP 回读确认媒体字节与 PNG 完全一致；source mapping 修订为 2，图片路径为相对路径；不存在 xl/charts 部件。

真实命令：`MPLCONFIGDIR=/tmp/xlsx-static-chart-mpl PYTHONPATH=/home/junge/pros/smart_reporting .venv/bin/python /tmp/xlsx-static-chart-probe.py`。输出：`preflightWarnings=[]; pngSize=[1800,1050]; embeddedImages=1; preservedB2=10; replacementRevision=2; nativeChartParts=[]`。

### 纯 bytes/base64 可行性

脚本 `/tmp/xlsx-static-chart-bytes-probe.mts`。从上一探针服务器生成的 PNG 得到 base64，解码为 Uint8Array，核对 SHA256 后直接调用真实 `applyStaticImage`；创建后沿用其返回 mediaPart 替换，再导出 `/tmp/xlsx-static-chart-probe/pure-bytes.xlsx`。

真实命令：`node --import /home/junge/pros/smart_reporting/smart_reporting/reporting/workbook_engine/node_modules/tsx/dist/loader.mjs /tmp/xlsx-static-chart-bytes-probe.mts`。结果：PNG 40010 bytes；base64 53348 字符；创建及替换均为 `xl/media/image1.png`。独立 openpyxl/ZIP 回读：`image_count=1, B2=10, embedded_png_exact=True, native_charts=0`。

第一次纯 bytes 调用遗漏四个 offset 字段，产生 undefined XML 并被 openpyxl 丢弃；补全 `fromRowOffset/fromColumnOffset/toRowOffset/toColumnOffset=0` 后回读通过。核心引擎依赖完整类型契约，不替代 API 边界校验。

## 后续最小安全协议

建议使用专用服务端 createStaticChart 任务，客户端只声明：expectedSha256、当前 operations/draftSha256、源 sheet/range、目标 sheet/range、显式标准 form/title/列映射及已确认单位。所有范围必须以合并人工草稿后的服务器预览为准，不能从当前网格推断完整数据。

服务端在既有会话作用域中冻结输入、生成 chartId/imageId/revision 和相对资产身份，复用标准编译/执行能力，核验 PNG/JPEG 解码后把资产登记为该会话和该草稿的服务器产物。响应只给 opaque assetId、候选身份、预览和告警，不能接受或返回宿主路径作为授权凭据。

客户端可持久化的候选操作应引用 assetId、图片身份和目标范围；服务端保存时再确认 context/draft/资产归属及身份。若内部 Node 桥必须采用纯 JSON，可由服务器把核验后的 bytes 序列化为 base64，内部严格校验 SHA256、长度、图片真实格式和完整锚点后调用 `applyStaticImage`。base64 只解决传输，不能提供来源或作用域真实性；不得把任意客户端 base64 当成已批准的 Matplotlib 图。

纯 bytes 底层不会生成 source mapping，也不会等比拟合或验证实际图片格式。生产实现应复用/抽取现有 `applyStaticImages` 的核验、拟合和溯源行为，避免复制另一套图片嵌入引擎。替换 mediaPart 必须由当前工作簿的受信任 source mapping 解析，客户端不可指定。

## 不可跳过的适配与验收

## 原生作用域接入设计补充（2026-11-11，只读调查）

此设计不代表生产协议已开放。本轮不新增依赖、`@sheets-web` 包、原生 OOXML 图表或 Plotly，也不添加尚无宿主调用的 helper。当前只能复用下列内部能力，不能将已有服务直接组合成已交付的图表入口。

1. **冻结当前草稿与授权范围。** `NativeWorkbookAIService.start_edit` 已把 `context.digest()`、原文件 SHA256、完整 operations、selection、scope 与 requestId 绑定；`_prepare_job` 调用 `NativeEditorService.preview`，由服务器把人工未保存操作应用到原文件。新图数据应从同一预览字节提取并冻结为带哈希的列/行 JSON，不能信任前端传来的 cells 或按 `readWorkbook` 的 null 公式投影猜数据。没有可信公式结果时返回具体诊断，保持草稿不变。
2. **确认标准作图契约。** 服务器生成 chartId/imageId、不可变输出路径和 revision；用户或受约束规划器只选择 form、标题、列映射及已确认单位。复用 `standard_charts.standard_edit_plan` 构造 `ChartInputMaterialization`，再走 `standard_visualization_preflight` 或现有 `runner.run_standard_visualization`。前者只是编译，不等于完成执行、图像检查和资产登记。优先接一类已实证的 bar 图，缺失单位不能自动补造。
3. **登记原生图资产。** 资产键应绑定 `NativeEditorContext` 的 documentId/revision/scope、基础 snapshotSha256、chartId/imageId 和图修订，并保存图像、脚本、输入文件的 size/SHA256、MIME、目标范围及源范围。浏览器只收到 opaque assetId、作用域预览 URL、候选身份及告警。读图与保存时重新核对 context、归属和实际字节身份。`ReportEditorService.read_asset` 当前只认证 Markdown 报告 render.images 或同报告改图登记，不能充当原生资产服务；`ChartEditRecord` 还要求底图与报告身份，不能伪造 Markdown 上下文复用。
4. **候选预览与采纳。** 复用原生异步任务、事件、取消与 `NativeAIService.accept_edit` 的过期候选验证：基础 operations 和 source SHA256 变化则旧候选失效。服务器在预演和最终保存时将已登记 assetId 解析成内部可信图片操作，复用 `delivery.xlsx.patch_workbook` 的 `applyStaticImages` 核验、拟合和 source mapping。客户端不得指定宿主 path、mediaPart 或把任意 base64 作为可信图。采纳加入同一 NativeDraft 历史事务，预览/保存失败保留原文件和人工草稿。
5. **保存与重开。** 最终保存重新解析同一作用域资产及当前 source mapping，替换只允许绑定的 imageId/目标范围；新修订保留所引用资产及来源身份。先验证 PNG/JPEG 真实格式和哈希再调用已有图片桥，不能仅靠 bytes/base64 的可传输性认定可信。

当前明确阻点：`WorkbookAIProposal` 不声明图片操作，选区 `_within_selection` 只允许 `applyCellEdits`；`native_office._XLSX_FIELDS` 未开放 `applyStaticImages`；`NativeEditorService` 与 `native_api` 没有原生图资产登记、预览及解析接口。当前原生 accept 只合并普通 operations，并没有替代资产作用域检查。完整入口必须先明确一个原生资产授权及服务器解析边界，不能仅把图片操作加入白名单。本轮未修改这些协议。

以上适配的最小验收仍是同一链路：冻结含人工编辑的数据 → 生成一张 Matplotlib PNG → 作用域预览 → 草稿变化使候选失效 → 正常采纳可撤销 → 保存新修订 → 重开及独立 ZIP/Excel 回读确认一张图片、字节身份正确、无新增 `xl/charts`。

- 标准编译器真实拒绝未知单位的双系列输入：`standard_axis_units_incompatible`。不能给任意工作簿自动补元、百分比或可加性；缺失元数据应让用户确认或给具体诊断。业务语义问题保持软告警，不阻断已有报告产物链接。
- column→bar、bar→barh、doughnut→donut 可显式映射；area 与 stacked-area、combo 与 stacked-total 语义不同，不可静默等价；雷达量纲/范围、饼图可加性、散点 X/Y 均需显式契约。当前仅实证 bar 创建与图片替换，不能宣称全部九类完成。
- 须验证未保存人工单元格修改进入图数据；旧候选在草稿变化后失效；不同会话 assetId 不可复用；图片字节变化拒用；替换不新增第二张图片；失败保留原图和既有文件。
- 须补浏览器预览、候选接受/撤销、保存新修订、重新打开与最终 XLSX 图片回读。当前两条脚本没有覆盖 UI，也没有创建修订或发布下载链接。
- 本轮未执行完整测试，未变更 native 路径白名单、Ribbon/main、共享构建产物，未 commit/push/deploy。
