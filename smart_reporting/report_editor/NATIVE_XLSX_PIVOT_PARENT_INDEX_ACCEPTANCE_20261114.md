# XLSX 透视父级百分比与指数专项验收

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地基础 `1e4a0a34` 加工作区改动。日期 2026-11-14，对应 P04 的限定子集，整体 P04 为 partial。

## 交付与兼容性修正

新增父行百分比 `percentOfParentRow`、父列百分比 `percentOfParentCol` 和指数 `index`，贯通计算、schema/state、OOXML、外部读取、刷新及实际源字段窗格。连同原有三种百分比，共六种 ShowAs 加普通值。

父级百分比按当前行／列前缀移除末层后的真实父域计算；指数为 raw×grand/(rowTotal×colTotal)。无值或零分母为空。百分比默认 0.00%，指数默认 General；显式格式优先。用户清空既有格式并切到指数后，输出格显式重置为 General，避免沿用旧百分比样式。

固定源把父级百分比直接写入 core `dataField@showDataAs`；该枚举不属于标准 ST_ShowDataAs，独立 openpyxl 枚举及微软 Open XML SDK schema 均不接受。此批没有复制这处源限制：省略 core `showDataAs` 属性，父级模式写入 `dataField/extLst/ext/x14:dataField@pivotShowAs`，扩展 URI 为 `{E15A36E0-9728-4E99-A89B-3F7291B0FE68}`。指数仍用标准 core index。[CT_DataField 完整约束](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/9fa014b6-505d-4aec-baf5-9473e2b3dd63)明确要求存在 `pivotShowAs` 时不得同时设置祖先 `showDataAs`；后续 RED2→GREEN7 已覆盖属性缺省要求，三份浏览器下载文件也已重新生成并独立回读。

依据：[MS-XLSX2.2.4.5 Pivot Table](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/aafe627a-ed81-4c50-98ef-78084230b952)、[ST_PivotShowAs](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/f5b294f2-a168-46c3-b9a9-8e4f0132b78d)，以及 dotnet/Open-XML-SDK x14 CT_DataField／core DataFieldExtension 定义。检索文件 Git blob 身份见 artifact 的 reference-evidence.json。未宣称运行完整 .NET OpenXmlValidator。

外部读取按 XML namespace、层级和 URI 识别扩展，支持前缀别名；未知模式、重复／畸形扩展不退化成 normal 并允许覆盖，而是进入宿主只读保护。独立审查复现并修正 foreign extLst namespace 漏查。

## 验证

- 初始 9 项计算／真实文件／UI 用例 RED；修正后通过。再以 RED2 验证标准枚举／扩展写入契约，RED1 验证 namespace 容器，审查 RED1 验证 foreign extLst，格式 RED1 验证百分比到指数的 General 重置，均修正。
- 最终引擎 **55 通过**，前端 **86 通过**；两端实际导入／测试闭包严格 TypeScript 检查通过。未重复完整套件或全应用构建。
- 固定种子 100 份25行数据、两层行轴＋两层列轴，三种模式共 **300 组本地／固定源数值矩阵一致**（含分组、小计、总计，数值相对容差1e-12）。只比较数值／布局，XML 扩展与 General 重置是必要的本地正确性适配。
- 真实 Chromium `154.0.8037.57` 选择三种模式、应用、实际 Blob 下载并读取保存字节重开；无 pageerror。指数场景通过真实字段设置清空从前一模式继承的数字格式，验证 General 重置；有意保留的显式格式仍优先。
- 三份下载经独立 openpyxl、ZIP/XML 回读，F2 为 1/4、1/3、5/6；前两份格式为 0.00%，省略 core `showDataAs` 并使用 x14 父级模式；指数为 General/core index。实际数值、状态、URI／namespace／属性均一致。没有用本地 reader 代替独立校验。
- 同模型独立审查发现的 namespace 问题已复现修复并复核；格式修正复核无重要发现。

## 范围与证据

`/tmp/xlsx-pivot-parent-index-20261114/` 包含实际组件／引擎的隔离浏览器源码、构建 metafile、脚本、3 份下载文件与截图、browser.json、独立回读、300 组源对照及引用证据。source-binding.json 绑定本批代码／测试和浏览器 bundle。测试日志 `/tmp/xlsx-pivot-parent-index-{red,xml-red,namespace-red,review-red,format-red,format-green,exclusive-red,exclusive-green,engine-final,frontend-final,ts,engine-ts}-20261114.log`。

仍缺八种基字段模式：percentOf、percentOfParent、difference、percentDiff、runTotal、percentOfRunningTotal、rankAscending／Descending，以及 baseField/baseItem 配置、计算和保存。旧版／其他编辑器不支持 x14 或二次保存丢扩展的行为未签收；没有完整应用服务／数据库修订／provider 或桌面 Excel 执行证明。整体 XLSX 对齐仍 active，未提交／推送／合并／部署。
