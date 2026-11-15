# Word 大小写与 XLSX 文本分列验收（2026-11-09）

沿用 GenOffice 固定版本 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，本批追加高频命令子集，不代表完整 Word/XLSX 对齐完成。没有提交、推送或部署。

## Word

- 开始页更改大小写菜单：句首、lower、UPPER、Title、toggle、半角、全角；标签、转换函数和 popover 关闭机制均复用固定源。`editor/case-transform.ts` 原样迁入并登记原始／本地 SHA。
- 仅同一有唯一来源锚点的可编辑正文段落内非空文字选区；整段字符格式须统一，不含链接／复杂内联对象。保留原 marks、选区和单次撤销，继续经过原生事务守卫及 replaceParagraph 身份校验。
- 此限制避免现有 replaceParagraph 按原 run 长度重分配文字时，ß→SS 等变长转换造成混合格式错位；未扩展保存协议或绕过守卫。表格、跨段、混合格式和快捷键循环仍未开放。
- `src/docx-case.test.tsx`：8项真实 GenOffice 扩展／Ribbon／native guard 测试，七种转换、变长选区、格式、回放、撤销重做、部分选择、只读与混合格式限制。原 Home popover 4项回归亦通过。

## XLSX

- 数据工具四种字面分隔符（逗号、分号、空格、制表符），保留连续分隔符中的空字段。当前 Univer 0.25.1 无上游调用的 split-text-to-columns 命令，复用项目既有 textToColumnChanges 规划器，再以一次官方 set-range-values 命令写入。
- 单列选区，来源最多2000行，输出最多2000单元格；展开输出前按非空行数×最宽字段数预检。所有校验先于写入；公式／共享公式／富文本来源、右侧已有值／公式／富文本、合并区域、越界、受保护工作表拒绝并给出原因。
- typedCsvValue 保留前导零，数字和 Boolean 按类型写入，等号开头的字段显式作为文本。保留已有样式和批注。Univer 内部带 Boolean 类型的1/0在来源读取与保存回读边界还原，避免二次分列或保存时变成数字。
- 不提供 CSV 引号限定规则、自定义分隔符向导、覆盖右侧数据确认或自动扩列；不是完整 Excel 分列向导。
- `src/workbook-main-fill-goto.test.ts`：最终12项，包含既有fill／goto／flash及7项新增分列场景；真实 Univer 命令、撤销重做、NativeDraft恢复、applyWorkbookOperations保存／引擎回读。另 Ribbon21项、格式9项、clear2项回归通过；clear测试包含独立openpyxl回读。

## 浏览器与独立文件证据

- `DOCX_INSERT_CASE=case node smoke/docx-insert-gui-smoke.mjs`：Chromium 140.0.7339.16 实际点击大小写菜单，粗体straße→STRASSE，撤销重做、刷新草稿、保存下载、真实Python patch_docx、python-docx回读、修订2重开通过。产物位于 `/tmp/docx-insert-gui-xLBW6q`，首段run为 `STRASSE / bold=true`。
- `WORKBOOK_RIBBON_CASE=split node smoke/workbook-ribbon-gui-smoke.mjs`：同版Chromium实际选择两行并分列、刷新草稿、保存下载，经真实Python patch_office和openpyxl独立回读为 `[[Ada,001,true,=A9],[Grace,42,false,null]]`；001保持文本，=A9类型为s，B1粗体／批注及范围外D5公式保留。
- 两个场景pageErrors为空。HTTP context/file/preview/save登记及下载路由为替身，实际文件转换和下载解析为真实执行；不代表生产HTTP、数据库、发布授权或部署验收。

## 复核与检查

独立复核发现并修复两项P2：Boolean来源类型丢失、输出展开后才检查预算。新增真实二次分列Boolean回归和6行×32766逗号的大输入预检回归通过；复核已确认关闭，未发现新的实质问题。

定向测试合计56项通过（54项相关回归＋新增2项边界），不运行完整套件。`npm run build`（tsc＋Vite）通过，Vite构建39.01秒；`npm run check:budget`及`git diff --check`通过。仍有既有Univer getSnapshot弃用提示、构建依赖注解／循环chunk／chunk大小提示，未作为本批产品改动扩展处理。
