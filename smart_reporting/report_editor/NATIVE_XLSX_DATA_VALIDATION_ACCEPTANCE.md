# XLSX 数据验证：官方面板、文件读写与结构迁移

日期：2026-11-09。对齐固定 GenOffice ref
`f8c17004fb730df11f0f743164ffd8b4281bb38c` 的官方 Univer 数据验证面板，
以及 `packages/xlsx-gateway/src/gateway/xlsx-dv.ts`。本批不关闭 Word/XLSX 全量目标。

## 已接通

- 数据页“数据验证”打开官方面板；规则通过 SHEET_DATA_VALIDATION_PLUGIN 加载，
  官方编辑/删除命令产生完整工作表规则快照，沿草稿、桥接、Python native 白名单保存。
- 读取 legacy/x14 验证，支持整数、小数、列表、日期、时间、文本长度、自定义公式和
  仅提示规则；保留多区域、允许空白、输入提示、错误提示、错误样式和下拉显示语义。
  OOXML 省略的 between 操作符显式投影；引用公式补 Univer 所需等号，数值常量不变。
- 列表常量保留空格；未知属性、未知子元素、容器设置和不可无损投影的来源规则
  标为该表数据验证只读，保留原文件内容。
- 行列插删迁移 legacy/x14 目标范围及引用公式，规则消失后更新 count、清理空 DV 扩展。
  跨表引用与重命名通过官方 SheetInterceptorService 并入原结构操作的 undo/redo；
  文件引擎同步处理 xm:f，避免实时旧公式覆盖正确保存基线。
- 修改前预检上游无法保存的多选列表、每表10000规则、每规则10000范围和8MiB草稿预算。
  官方多选列表选项仍可见，但尝试应用时明确拒绝，已有规则和草稿保留。
- 刷新恢复后等到 Univer Rendered 阶段才打开面板，避免出现组件键名占位文本。

## 已执行验证

- 引擎 writer/reader/bridge：35项通过；结构与工作表操作原有定向回归19项通过。
- 前端 adapter/main/结构：25项通过；审查新增预算故障注入1项通过，含官方命令编辑、撤销重做、删除整条规则后编辑剩余规则、
  跨表插行与重命名、受保护目标表引用迁移、公式字符串保留、草稿恢复及保存回读；Ribbon另21项通过（后续Ribbon未修改）。
- Python test_workbook_data_validation.py：2项通过，实际经过 patch_office 白名单和
  工作簿引擎，并用 openpyxl 独立检查范围、提示、错误样式、允许空白、值和规则清除。
- Chromium 140.0.7339.16：WORKBOOK_RIBBON_CASE=dv 浏览器验收通过。
  面板中将B2:B5整数大于0改为大于5，刷新恢复草稿，真实Python保存并openpyxl回读
  formula1=5、prompt=填写正整数、allowBlank=False，pageErrors=[]。截图
  `/tmp/genoffice-dv-panel.png`。HTTP为测试替身，未验生产鉴权及数据库登记。
- TypeScript引擎校验、bridge bundle、前端build、预算契约和git diff --check通过。
  新增DV读写使workbook-engine实测414.7KiB，预算396→416KiB；官方面板共用图标
  实测274.2KiB，预算274→275KiB；普通入口与其他包预算未扩大。
  既有chunk-size、循环块、Radix、zod注释和getSnapshot弃用提示仍存在。

## 剩余边界

- 多选列表不能写入XLSX；checkbox按固定源writer降为两值列表，重开不保证复选框外观。
- disablePrompts/xWindow/yWindow、未建模属性、以等号开头的列表字面常量仍为只读边界。
- 定义名称/结构化引用列表的上下文解析、复杂宿主行为和全部规则类型的逐项GUI验收
  尚未完成；浏览器本批仅验整数规则编辑，组合结构迁移依赖真实Univer集成测试。
- 浏览器已验草稿刷新和下载文件独立回读，保存后的修订2页面重开亦通过，官方面板仍显示整数大于5。
- 不据此宣告数据验证全部选项或Word/XLSX全量对齐完成。

## 审查修复续验收

- 受保护目标表的跨表插行会连带更新验证引用；按实际从属 mutation 参数对象身份登记，
  不根据 source 文本放行。用户直接编辑仍拒绝；插行、撤销、重做、草稿恢复及保存回读通过。
- 本簿限定符只在引用 token 中规范化，字符串常量保持原样，undo 保留原始公式。
- 本次25项定向测试通过；预算修复后重跑受影响数据验证6项均通过（包含新增预算故障注入），
  最终前端build与预算检查通过，引擎typecheck和bridge bundle通过。
- Chromium真实保存后重开修订2，面板显示整数大于5，pageErrors=[]；HTTP仍为测试替身。

- 结构操作的验证从属更新在基础行列 mutation 执行前预检预算与可落盘性；失败时行数、
  公式、撤销栈与草稿均不变。已登记从属更新执行时不重复扣预算。

- 只读复审确认保护迁移、参数对象身份与预算前置检查的修复；本轮未发现新的阻断问题。

## 全局定义名称列表续验收

- 官方列表校验接入实时全局名称解析，支持大小写无关的裸名称与别名链；
  未知名称、循环和未投影的工作表局部名称不作为合法来源。仍复用官方范围相交校验。
- 修复 Univer 0.25.1 间接名称变化不使词法缓存失效的问题：只为计算注册展开副本，
  供结构引用服务读取的公式信息恢复原文，模型、草稿和保存操作保持 `=Choices`。
  合法单单元格引用 `=A1` 先由官方引用识别能力处理，不误判为未知名称。
- 真实无头 Univer 回归覆盖：Choices→Alias 的换绑、撤销/重做、来源单元格更新、
  编辑提示后插行、工作表重命名及撤销/重做、草稿恢复和引擎保存回读。
  结构迁移后仍保留 `=Choices`，Alias 正确迁移至重命名表的新行。
- 相关四文件共28项测试通过；修复前曾分别复现别名不刷新、插行改写名称身份、
  `=A1` 被拒三类失败。最终源码经只读复审，未发现新的阻断问题。
- Chromium 140.0.7339.16 的 `WORKBOOK_RIBBON_CASE=dv-names` 通过：
  名称管理器将 Alias 从 Summary!$A$1:$A$2 改为 Summary!$A$2:$A$2，
  官方列表面板显示 beta；修改允许空白、等待草稿持久化、刷新恢复、真实Python
  patch_office 保存及 openpyxl 独立回读通过，修订2实际重开面板仍显示 beta，
  pageErrors=[]，截图 `/tmp/genoffice-dv-names-panel.png`。
  文件公式按OOXML写作 `Choices`，重新加载模型显示 `=Choices`；名称身份未展开。
  HTTP仍为测试替身，未验生产鉴权与数据库修订登记。
- 最终前端TypeScript/build、现有预算和git diff --check通过，未扩大预算。
- 仍缺表格结构化引用列表、工作表局部名称及完整规则类型逐项GUI验收；
  不据此关闭数据验证全项或Word/XLSX全量目标。

## 表格结构化列表续验收（2026-11-09）

- 按真实 worksheet tableParts 投影官方 Table 资源；列表支持简单 `=Staff[Name]`
  及 `=staff[[NAME]]`，大小写无关，数据区排除声明的表头和汇总行。计算副本展开
  为带引号的绝对范围，规则/草稿/保存保留结构化引用身份；名称别名可转引表列。
- 真实 Univer 测试覆盖无表头/有汇总行、插行与来源值更新、表名所在工作表重命名、
  撤销重做、草稿恢复及引擎保存。修复不配对方括号被误当有效来源的问题。
- 官方默认蓝色及边框会覆盖文件单元格外观；已用官方 userThemes 配置中性主题
  避免额外覆盖。这不代表 OOXML tableStyleInfo 已完整渲染。
- 审查发现并修复结构一致性问题：删除表头/汇总行/全部数据行、全部列在基础
  mutation 前复用保存引擎 shiftTablePart 预检；表内插列复用引擎 ColumnN 名称
  并同步表头，同次撤销重做；删列撤销重建表格时按参数对象身份恢复原生汇总行
  元数据。失败时网格/表格/撤销栈/草稿不变有实际回归。
- 四文件36项定向测试通过，TypeScript校验、前端build、现有包体预算与预算契约、
  bridge bundle及 git diff --check通过；未扩大本批预算。
- Chromium 157.0.8103.38：WORKBOOK_RIBBON_CASE=dv-tables通过。官方面板显示
  Ada，修改允许空白、等草稿落盘、刷新恢复、真实Python patch_office、openpyxl
  独立回读，再实际打开修订2面板仍显示Ada。文件验证公式 Staff[Name]、表格
  Staff/A1:A3/Name/TableStyleMedium4均保留，pageErrors=[]；截图
  /tmp/genoffice-dv-tables-panel.png，日志 /tmp/genoffice-dv-tables-gui.log。
  新版Chromium本机HMR的LocalNetworkAccessChecks仅在测试浏览器启动参数中关闭。
  HTTP仍为测试替身，未验生产授权与数据库修订登记。
- 仍缺完整Table Design操作写回、表头更名与列元数据同步、原生表格样式呈现、
  完整结构化引用语法、局部定义名称和所有验证类型逐项GUI验收；全量目标未关闭。

### 跨表底删行复审修复

复审发现官方插件按完整删除行数缩表，删除范围跨出表底时实时数据区短于文件
保存结果。已复用 shiftTablePart 输出范围修正对应官方 redo；真实回归覆盖
跨表底删除、列表值、undo/redo。四文件最终37项通过，最新类型检查/build通过；
前述36项为修复此边界前的记录。
