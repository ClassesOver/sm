# XLSX 透视表十一种聚合专项验收

参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地基础 `1e4a0a34` 加工作区改动。对应全域账本 P03。日期 2026-11-14。

## 本批交付与源语义

新增 `product、countNums、stdDev、stdDevp、var、varp`，与原有五种一起覆盖固定源十一种聚合。计算类型与默认标题、纯布局计算、状态 schema、OOXML `dataField@subtotal`、外部透视表读取映射、源字段窗格启用及宿主配置传递全部接通。真实文件创建、外部导入（移除本地状态后）、改源值刷新、改回 sum 均有定向测试。

保留源的数字转换：数值文本参与聚合，布尔值与非数字文本不计作数值；零与负值参与运算。空桶的数值计数为 0，其他新增统计为空。样本方差／标准差在 n<2 时返回空值；总体统计单值为 0。这是固定源的有界语义，Excel 的样本不足通常显示 `#DIV/0!`，未宣称与全部 Excel 统计错误／浮点边界等价。计算字段仍只能 sum，未随这批扩大。

## 验证结果

- RED：13 项纯计算、6 项真实文件、6 项 UI 选项测试分别失败；修复后对应测试通过。UI 首次探针有一处错误 CSS selector，修正后才记录禁用状态导致的有效 RED。实现前也更正刷新夹具中预期算术及无状态返回类型，未通过放宽产品断言取得通过。
- 引擎 9 文件 **66 项通过**，包括新聚合及既有创建、展开、刷新、计算字段、分组、控件与动态来源。前端 11 文件 **109 项不同测试通过**：首次合并运行 108 通过／1 失败；该失败是旧测试使用孤立 shared follower（缺 master），改为来源区外有合法 master 的共享组后，该刷新文件 11 项通过。原来的陈旧公式结果拒绝消息断言、输入不变断言均保留；不把重跑 10 个重合用例累加成新测试。
- 引擎和前端实际导入／测试闭包严格 TypeScript 检查通过。没有重复完整套件、全应用构建或资源预算检查。
- 固定种子 100 份、每份 25 行的混合数据，六种模式共 **600 组本地／固定源布局对照一致**（数字按 1e-12 相对容差）。范围是单层行维度、数据桶及总计；不是全部布局组合证明。
- 真实 Chromium `154.0.8037.57` 中，使用实际源字段窗格、宿主对话框及 XLSX 引擎逐一选取六种模式，应用并实际 Blob 下载六份 XLSX；每轮读取保存字节并重开，模式保留。值结果为乘积 8、数值计数 2、样本标准差 √2、总体标准差 1、样本方差 2、总体方差 1。无 pageerror。
- 独立 Python `statistics`/`math`、openpyxl、ZIP/XML 对六份下载文件逐一检查分组输出、总计、实际 `subtotal` 与持久状态；均通过。不是仅用本地 reader 回读自己写出的文件。
- 同模型独立代码审查无重要发现。

## 证据与边界

浏览器源码／构建 metafile／运行脚本／6 张窗格截图／6 份实际下载文件／独立回读脚本和 JSON、600 组源对照脚本及结果：`/tmp/xlsx-pivot-aggregations-20261114/`。`source-binding.json` 绑定本批代码／测试及浏览器 bundle；`browser.json` 明确记录隔离宿主范围。

测试日志位于 `/tmp/xlsx-pivot-aggregations-{engine-red,frontend-red,ui-red,engine-green,frontend-green,engine-final,frontend-final,refresh-final,ts,engine-ts}-20261114.log`。引擎身份更新于 `workbook_engine/UPSTREAM-PATCHES-SHA256.json`，Pane 身份更新于其目录 `LOCAL-ADAPTATIONS-SHA256.json`；冻结源清单未改写。

浏览器验收采用真实组件／引擎的隔离 harness，没有完整应用服务、数据库修订或真实 provider。额外 Show Values As、baseField/baseItem（P04）、自定义值标题（P05）仍开放；格式、所有维度／筛选组合、规模／浮点极值及完整生产保存链也未因本批被标记全通过。整体 XLSX 对齐目标仍 active。

改动未提交、推送、合并或部署。
