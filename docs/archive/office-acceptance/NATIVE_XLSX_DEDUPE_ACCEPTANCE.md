# XLSX 删除重复值验收（2026-11-09）

固定源：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c，apps/sheets/src/renderer/dedupe.ts 原样复制，SOURCE-SHA256.json 登记。对话框和执行语义参照 ExcelShell.tsx RemoveDuplicatesDialog 与 ribbon-actions.ts remove-duplicates。

## 行为

数据→删除重复值；所有选中列组成比较键，文本不区分大小写，值类型区分；默认保留第一行为标题。打开时冻结工作表 ID 与区域，确定时重新检查状态。仅压缩所选区域的值并清空尾部，不删除工作表整行。目标位置样式与批注保留；未移动且值相同的行不重写，移动公式按固定源写入其计算值。无可读取计算结果的公式/共享公式在比较前拒绝，提示先重新计算。

保护、合并区域、超过2000单元格和现有草稿预算预检拒绝；预算在读取选区矩阵前检查。一次 sheet.command.set-range-values，沿用官方撤销/重做与既有差分、草稿、保存链。

## 验证证据

- 新用例先红后绿；workbook-main-fill-goto.test.ts + workbook-ribbon.test.ts：37通过。覆盖标题、大小写比较、Boolean/数字/文本区分、冻结原选区、撤销重做、草稿恢复、XLSX保存回读、保护/合并/预算拒绝及公式未计算安全边界。
- npm run build（tsc + Vite）与 npm run check:budget：退出0。既有依赖注释、循环分块、分块大小与 getSnapshot 弃用告警仍存在。
- WORKBOOK_RIBBON_CASE=dedupe node smoke/workbook-ribbon-gui-smoke.mjs：Chromium 140.0.7339.16，通过真实按钮、对话框、刷新草稿、保存和下载；Python patch_office 写文件，openpyxl 独立回读。
- 输入 Name/Flag、Ada/true、ADA/true、Grace/false、Grace/false；结果 Name/Flag、Ada/true、Grace/false、空行、空行。A3粗体及位置批注保留，选区外D5公式=A2保留，pageErrors为空。
- 审查发现的未计算公式误判为空及清尾跳过问题已复现并修复。

## 边界

目前与固定源一样比较全部选中列，没有自选比较列界面；单次2000单元格。富文本来源沿用既有安全预检拒绝。手动计算模式使用当前可读取计算值；无结果时不猜测。浏览器验收的HTTP context/file/save路由为替身，文件补丁与下载解析真实，不代表生产鉴权/数据库/部署验收。
