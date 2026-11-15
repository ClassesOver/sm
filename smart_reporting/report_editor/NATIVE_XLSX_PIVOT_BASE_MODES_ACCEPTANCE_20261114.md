# XLSX 透视基字段／基项八种显示方式专项验收

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地基础 `1e4a0a34` 加工作区改动。日期 2026-11-14。对应 P04 后续增量，**P04 仍为 partial**。

## 本批交付

新增 percentOf、percentOfParent、difference、percentDiff、runTotal、percentOfRunningTotal、rankAscending、rankDescending，连同先前六种，十四种 ShowAs＋普通值全部启用。基字段／基项在 pane model、宿主标签配置、布局 definition、状态 schema、OOXML field/item 索引、保存重开和外部导入之间贯通。

差值／相对比例参照指定基项；累计和排名使用可见成员顺序，按外层成员／另一轴分组重新开始，排名并列采用 RANK.EQ 语义；跨基字段的小计／总计和基项自身空值规则匹配固定源。非法、非轴基字段和不存在基项在生成计划前拒绝。

外部 baseItem 先索引 pivotField.items，再通过 item.x 找到 cache sharedItems，不能直接当缓存下标。已保存的成员显示顺序按字段身份保留，避免刷新重排累计；无法核验的外部累计顺序转为只读。普通 n/s/b/m 缓存标签和空基项受支持；raw d/e 缓存基项仍受限。

分组选择器使用与计算器相同的 typed groupValue，数值分组和 1904 日期纪元的基项不再显示原始值。百分比默认 0.00%，非百分比显示方式在清空格式时重置 General，显式格式优先。显式 General 可输入，写 numFmtId="0"，外部导入／刷新后仍为 General；不把它丢成百分比默认格式。

原生 percentOf 写标准 percent；另外三个原生新增模式用 difference／percentDiff／runTotal。父级、运行百分比和两种排名用 Office2010 x14 扩展，共六种 x14 模式均省略 core showDataAs，遵循 [CT_DataField](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-xlsx/9fa014b6-505d-4aec-baf5-9473e2b3dd63) 的互斥约束。非 OLAP 不写 sourceField；相关输入及不合法扩展受到只读保护。

## 验证与审查

- 初始有效 RED 包括列轴八种计算、四种非法基参数、八条真实文件参数链和八条 UI 选项。行轴／隐藏成员九项测试最初误用被省略的重复外层标签定位，修正定位后才用于数值验收，数值期望未修改。最后纯基模式 21 项通过。
- Parser 的标准 percent 归一、非法 x14/native 模式和 OLAP 属性先 RED4 后通过；普通缓存基项／顺序／特殊 sentinel／空项等 13 项定向读取测试通过。
- 独立同模型审查发现外部重排后累计顺序丢失，真实文件 RED3 复现后修复，含差值基项的双重索引。再次审查发现 General 外部刷新丢失，原生及扩展模式 RED2 复现后补 id0 序列化／读取。两个分组／1904 UI 场景和显式 General 输入各有独立 RED→GREEN。
- 最终引擎 **93 项通过**（9 文件），前端 **110 项通过**（11 文件）；两端实际导入／测试闭包严格 TypeScript 检查通过。未重复完整测试套件或全应用构建。
- 固定种子 100 份26行数据，两层行轴＋两层列轴，八种模式分别以行／列字段为基字段，共 **1,600 组本地／固定源数值矩阵一致**，含源支持的标签筛选、分组小计、总计；数字相对容差1e-12。最初对照脚本错误地给源函数传入仅本地支持的第四个顺序／隐藏参数，导致行数差异；修正为双方共同 API 后验收，重排顺序另由独立实际文件回归覆盖。未放宽数值断言。
- 真实 Chromium `154.0.8037.57` 在实际源 pane／宿主对话框中逐一选择八种模式，实际选择 Item 基字段和 A 基项，清空默认继承格式，并追加百分比＋显式 General 场景；实际 Blob 下载 **九份 XLSX**，每轮读取字节重开，模式／基参数保留，无 pageerror。
- 独立 openpyxl、ZIP/XML 和手工数值期望检查九份下载：八种模式 B 成员分别为 2、0.4、10、1、30、0.6、2、1，基项自身空值／排名／比例亦检查；数字格式、baseField/baseItem、原生拼写、x14 URI／namespace 和不共存 core 属性均吻合。General 额外文件为数值2、General格式、numFmtId0。没有只用本地 reader 证明自己写出的文件正确。

## 限制与证据

仍开放的 P04 文件兼容边界：raw 外部日期／错误缓存基项直接投影、不可核验的显示顺序、旧文件未指定 dataField 格式时的继承语义。之前／之后特殊基项 sentinel 是固定源也拒绝的边界；OLAP sourceField 未提供支持。既有自定义格式限制、混合后缀标题碰撞、极端数值和所有布局组合未因本批被标记全通过。没有完整应用服务／数据库修订／真实 provider、桌面 Excel 或完整 .NET OpenXmlValidator 执行证明。

证据目录 `/tmp/xlsx-pivot-base-modes-20261114/` 包含浏览器源码／构建 metafile／脚本／九份实际下载及截图、browser.json、独立回读脚本／JSON、1,600 组对照脚本／结果、微软 CT_DataField 文档及参考身份。`source-binding.json` 绑定当前代码／测试与浏览器 bundle，`tested-sources/` 冻结这些文件的实际字节；RED／GREEN／最终测试与类型检查日志也已复制到目录。engine UPSTREAM-PATCHES 和 Pane LOCAL-ADAPTATIONS 哈希更新，冻结的原始源清单未改。

改动未提交、推送、合并或部署。全域 XLSX 对齐仍 active。
