# XLSX PR 集成验证

本轮产品与审计提交03a9f90d、f98829f6，合并默认分支code的f7180255后形成82c5c901。来源说明与哈希清单冲突均保留双方记录；workbook-read.ts自动合并后同时保留共享公式展开与拆分／冻结窗格几何读取，独立复核未发现重要集成问题。

对该组合执行：

- workbook_engine Vitest：shared-formula-reader及split-pane／paired-selection，32项通过。
- frontend Vitest：workbook-shared-formula-import、workbook-pivot-dimension-formats、pdf-search，21项通过。Univer提示使用save替代getSnapshot的既有警告保留，未改变断言。
- .venv pytest：test_workbook_ai_preconditions.py，28项通过，包括两个真实Python→Node引擎回读用例。环境缺少tsx，直接源码入口先导致这两项失败；随后用当前合并代码打包CLI，通过AGENT_REPORTING_WORKBOOK_ENGINE_DIR指向隔离bundle重验。系统Python没有pytest，实际检查使用仓库.venv。仅有既有imghdr弃用警告。
- 两端实际导入／测试闭包严格TypeScript通过；包含合并后的bridge及读取器。没有运行全应用构建或重复完整套件。
- 固定源inventory重验：483文本blob身份、479必需文件无缺失；158条账本sourceRow及分域计数一致；109条当前引擎哈希与字节一致。

早先每个专项的浏览器／独立文件回读身份保持历史状态，不伪称它们是在合并后完整应用运行。当前继承样式专项另有52前端／22引擎及四份真实浏览器文件证据，详见其验收文档。执行环境的集成日志、当前CLI bundle／metafile保存在/tmp/xlsx-pr-integration-20261114/；可审阅身份记录见XLSX_PARITY_AUDIT_20261114/pr-integration.json。完整应用／真实provider／桌面Excel链路仍未验收。

审计基线仍是1e4a0a34及固定源f8c17004fb730df11f0f743164ffd8b4281bb38c；合并新增行为并非自动被标成逐项对齐。普通网格继承样式、计算字段显示身份、数字表头、旧透视迁移及其余账本开放项仍保留。
