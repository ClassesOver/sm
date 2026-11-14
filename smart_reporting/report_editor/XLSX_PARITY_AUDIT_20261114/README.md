# XLSX 固定源全域缺口账本

参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地 `1e4a0a34` 加当前工作区，包括先前 Scatter 回退和 Line/Radar 描边修复。日期 2026-11-14。初始审计阶段只做静态核查；后续补缺有各自的测试/文件证据（见下方修复链接），不把历史验收算作当前重验。真实模型及生产同链仍未完成。各批 `source-binding.json` 绑定其验收时字节，后续同文件变更以最新专项为准，旧 artifact 身份保留。

**现已覆盖固定源的整个 renderer 文本树、主进程/preload/共享协议、Rust 与 gateway 源文件清单，并收敛成逐域账本；尚不能宣称逐参数、逐运行行为穷尽完成。** 14 项行为族仍需验证；85个导入适配器已逐项找到归属和本地对照，精确行为证据尚未全部闭合，明确见 [进行中状态](audit-progress.json)。本轮结果是已确认开发缺口与验证缺口的全域索引，不是完整 XLSX 对齐完成证明。目标保持 active。

## 可复核的覆盖边界

- 上游完整非截断树为文件宇宙；483份下载文本逐份匹配固定树 Git blob，479份必需源文件无缺失，额外4份共享实现也有身份核对。源码保存在 `/tmp/xlsx-exhaustive-20261114/source/`，仓库保留[路径与哈希](source-files.json)。
- renderer 363文件中358份文本已扫描；其余5个PNG只是明确登记的资源排除，不是漏读代码。Rust/gateway源码也在清单中；下载和AST扫描不等于每行语义已核验。
- [源声明](source-declarations.json)：2564处UI声明、260处命令调用声明；[本地声明](local-declarations.json)：199个工作簿专属模块、1055处UI声明、227处命令调用声明。包含动态表达式、重复声明与实现细节，**不能相减当缺口数，不能作为完成率分母**。
- [76个IPC通道](ipc-channels.json)全部分配到[28组宿主映射](host.md)及[逐通道记录](host-channel-map.json)。[99个DesktopApi方法](desktop-methods.json)还包含共享shell能力；[85处导入的运行时适配器调用](runtime-adapters.json)已全部进入[逐符号语义映射](runtime-adapter-map.json)，无未归属项；已实现、部分支持、缺少源修复及未验证影响分别保留，不把同名/异名认定为功能等价/缺失。
- 158条非AI能力族/存储记录分列下表；域间有交叉，例如CSV导出和存储身份、图表与打印，不能累加成独立功能数。AI另列13个工作簿工具、5个组合工具以及[56个DSL操作与字段](ai-operations.json)。动态用户附加技能不属于这18个固定基础工具的分母。

## 分域状态

`done_bounded`＝已存在的限定实现；`partial`＝已实现子集与明确差异；`missing`＝固定源确有路径、本地缺失；`source_boundary`＝源自身限制/未实现；`host_boundary`＝源支持但当前Web/授权宿主未提供，完整目标仍开放；`unverified`＝缺证据，不能直接当开发缺口。

| 账本 | 限定实现 | 部分支持 | 确认缺失 | 源边界 | 宿主边界 | 待验证 |
|---|---:|---:|---:|---:|---:|---:|
| [网格／格式／保护／审阅](core.md) | 26 | 10 | 5 | 2 | 0 | 5 |
| [公式／数据／透视](data.md) | 31 | 8 | 6 | 3 | 0 | 4 |
| [图表／绘图／打印](visuals.md) | 15 | 13 | 9 | 4 | 0 | 4 |
| [存储／规模／文件生命周期](storage.md) | 1 | 4 | 5 | 1 | 1 | 1 |

[条件格式／数据验证字段级续审](cf-dv.md)另有43条字段族记录，未与能力族相加。CF写入器与源文件SHA256完全一致；额外差异集中在导入投影、dxf边框/数字格式、小范围文本规则转换及DV解释策略。完整原始记录及稳定ID见 [capabilities.json](capabilities.json)；[AI工具／参数／生命周期](ai.md)和[宿主映射](host.md)单列，避免重复统计。

## 已确认缺口的处理顺序

| 优先级 | 具体差距 | 证据入口 |
|---|---|---|
| P0 正确性 | 源 `gxRedactions.json` 及派生公式屏蔽未转换成本地AI输入；源 `expectedValue/expectedFormula` 字段已在[后续修复](../NATIVE_XLSX_AI_PRECONDITIONS_ACCEPTANCE_20261114.md)中补齐纯单元格批次检查；原生/结构前缀后的条件写入仍受限。范围授权/整稿CAS与此语义独立。未宣称生产数据泄露或越权已发生。 | core.md屏蔽行；ai.md；ai-operations.json前两项 |
| P0 正确性 | 不支持函数的缓存结果回退、排序后的相对公式修复仍开放；shared-formula follower展开与组内安全保存已在[后续修复](../NATIVE_XLSX_SHARED_FORMULA_ACCEPTANCE_20261114.md)中交付（eager模型）；普通柱／条图stacked/percentStacked已在[后续修复](../NATIVE_XLSX_STACKED_BAR_ACCEPTANCE_20261114.md)中交付；Line/Area/Combo仍开放；打印缺浮动图表/图片/形状。 | data.md F07/F08/T02；visuals.md V09/V39 |
| P1 数据功能 | 外簿选区relay；CSV显示值导出／独立CSV保存；源已实现的web query刷新；透视十四种ShowAs与基字段／基项的常规路径已在[后续专项](../NATIVE_XLSX_PIVOT_BASE_MODES_ACCEPTANCE_20261114.md)接通，外部日期／错误缓存基项投影与旧文件未指定格式的继承语义仍受限；P04保持partial。自定义值标题已在[后续专项](../NATIVE_XLSX_PIVOT_CAPTIONS_ACCEPTANCE_20261114.md)中交付。六种额外聚合已在[后续修复](../NATIVE_XLSX_PIVOT_AGGREGATIONS_ACCEPTANCE_20261114.md)中交付。 | data.md F03/D03/D06/P03-P05；storage.md S11 |
| P1 视觉功能 | Line marker开关/图形与blank modes、combo描边/标签/趋势线/命中、线性趋势线、Area负值基线与堆叠、图例、图表区/轴文字；一般形状/文字框/自由绘制、排列与视觉对象剪贴板、单元格图片、OLE预览、图片粘贴/截图。 | visuals.md逐项行，源不支持的图形另列边界 |
| P1 编辑审阅 | 富文本run投影与编辑；拼写/F7及翻译入口；加密工作簿打开/密码修改；保护权限/密码和受限范围密码；部分线程批注/旧便签入口未接全。 | core.md；有完整表格和来源符号 |
| P1 AI任务 | 范围copy/fill/move/convert、shape/image与部分sparkline/标签工具语义；regex搜索、参数界限；持久chat/任务恢复/澄清继续；附件、新文档、搜索/生成图与可见网格MCP宿主能力。显式采纳是现有授权边界，不因对齐自动改为自动应用。 | ai.md；host.md；56操作字段表 |
| P2 规模与宿主 | 磁盘索引/按范围加载、保留压缩条目的流式保存、大编辑分块提交、独立恢复文件；xls/ods/ots/SpreadsheetML导入；直接PDF、设备打印、份数/逐份等宿主能力。 | storage.md；host.md；不能只提高限制常量代替实现 |

## 旧清单更正

1. 外链Update/Break/重定向已存在；真正开放的是跨簿range picker、复杂依赖和web query刷新。
2. 透视表创建编辑、六页签单元格格式、完整Paste Special、线程批注、批注图片、受限范围基础CRUD已有实现；不能再按全缺处理。各自密码/模型/入口边界仍保留。
3. Scatter首系列标签回退、条件关闭及Line/Radar描边已在先前批交付；本轮引用其准确范围，未重复测试。
4. 页眉页脚图片已进入打印HTML；真正缺的是浮动图表/图片/形状快照。
5. 固定源普通窗口组只有冻结；工作表背景图没有可执行编辑/保存能力；不能用本地额外禁用按钮证明源迁移遗漏。core.md末尾有背景图专门复核。
6. 固定源不保存原生切片器/时间线控件本体，而本地有自有持久化路径；原生Excel行为仍待验证。源不支持的3D/exotic重建、向量公式、OLE激活、任意Power Query/M不是已确认迁移缺口。
7. Scatter源只绘制圆点，不能列成“任意marker glyph缺失”；Line glyph差异则有确证。源与本地均按各线系列长度归一横坐标，不将此当迁移缺口。

## 重现、验收与下一步

运行 [inventory工具](../frontend/scripts/xlsx-parity-audit-inventory.mjs)：

```sh
node smart_reporting/report_editor/frontend/scripts/xlsx-parity-audit-inventory.mjs \
  --source-root /tmp/xlsx-exhaustive-20261114/source \
  --tree /tmp/xlsx-exhaustive-20261114/tree.json \
  --output-dir smart_reporting/report_editor/XLSX_PARITY_AUDIT_20261114
```

工具复用现有TypeScript/JSDOM清单器，不执行页面/模板表达式；检查非截断树、479个必需源文件与每文件Git blob，缺文件或身份不符即失败。源码下载由GitHub连接器按固定ref完成，重现需相同快照；原始下载补出的patch尾换行仅在去除后恰好匹配源blob时归一，未用修改源代码取得哈希通过。

初始清单阶段仅运行语法检查、静态清单生成和JSON/引用/分母一致性检查；后续产品修复分别记录定向测试和实际文件证据，不算作完整应用或真实provider／生产故障注入通过。四个同模型分域审计及存储续审提供独立分析；总表独立复核发现并已更正CSV归属/状态矛盾及.xlsm保全缺少责任行，两项均有显式记录。所有`unverified`记录和适配器声明有明确待办，不标成通过。下一轮按进行中状态逐项收敛，代码补缺需分别RED→GREEN与实际文件/宿主验收。宏启用工作簿保全另见storage S13：固定源保留.xlsm/VBA，本地导入策略明确拒绝，列为宿主边界，不能用对齐名义直接去除校验。未提交、推送或部署。

布尔源值／缓存类型后续修复见[专项验收](../NATIVE_XLSX_PIVOT_SOURCE_BOOLEANS_ACCEPTANCE_20261114.md)。新增 P12 明确登记三类已复现的数字格式维度标签差异，保持 partial；未把这些诊断文件计为修复通过。

报表筛选字段切片器／时间线已完成[限定验收](../NATIVE_XLSX_PIVOT_PAGE_CONTROLS_ACCEPTANCE_20261114.md)，P09 更新为 done_bounded；全选、保存重开和原生控件刷新已接通，零交集拒绝等边界保留。

引擎哈希清单中八条历史过期记录已核对为与本地基线逐字节一致并更正，旧／新身份见[更正证据](engine-manifest-baseline-corrections.json)；仅修正元数据，不新增行为通过或改写历史 artifact 绑定。

P12 的显式单元格格式维度标签已完成[后续限定修复](../NATIVE_XLSX_PIVOT_DIMENSION_FORMATS_ACCEPTANCE_20261114.md)：编号前导零、1900/1904日期、缓存及筛选／基项身份一致。继承样式、计算字段、数字表头和旧文件迁移仍开放，P12保持partial；此前三份诊断仍是历史失败证据。

P12 的行／列继承数字格式已在[后续专项](../NATIVE_XLSX_PIVOT_INHERITED_FORMATS_ACCEPTANCE_20261114.md)补齐透视读取路径；普通网格导入不在该验收范围，计算字段、数字表头与旧状态迁移仍开放。
