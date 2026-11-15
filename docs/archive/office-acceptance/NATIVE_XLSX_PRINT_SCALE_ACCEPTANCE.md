# XLSX 打印百分比窄验收

2026-11-10。固定完整源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。源能力与边界见 [只读调查](NATIVE_XLSX_PRINT_SCALE_INVESTIGATION.md)。本次实现和验收为独立确认式打印百分比入口，不是完整源 PrintDialog。

## 最终 built 结果

root 统一构建并通过预算、契约后冻结产物；相关日志 `/tmp/office-alt-print-statistics-{build,budget,contract}.log`。验收仅启动 Vite preview 4271，未重建、未修改生产代码或引擎。

执行 `node smart_reporting/report_editor/frontend/smoke/workbook-print-scale-built-smoke.mjs` 最终 exit0，日志 `/tmp/workbook-print-scale-built.log`。Chromium `140.0.7339.16`，真实保存3次，console/pageerror均为空，加载的121个JS资源全部HTTP200且SHA256与本地静态文件一致。

清单 `/tmp/workbook-print-scale-built-manifest.json` 记录日志和产物SHA256。证据目录 `/tmp/print-scale-built-5hZxNX/` 保留各比例 result JSON、下载XLSX、实际打印HTML（确认后、草稿刷新后、新修订重开后）、重开截图及 assets.json。

| 设置 | 新修订 | 打印HTML页数 | 原30pt首行实际高度 | XML scale | XML fitToPage |
| --- | --- | --- | --- | --- | --- |
| 10% | 2 | 1 | 3pt | `10` | 缺省（有效false） |
| 100% | 11 | 1 | 30pt | 缺省（有效100） | 缺省（有效false） |
| 400% | 21 | 8 | 120pt | `400` | 缺省（有效false） |

下载SHA256：

- 修订2：`1008e699bd9af60260308fffe3c3bec72226cff421b9c17124336d69a746048e`
- 修订11：`444cb58d21321f4b59dbd04189a864e66cbb8855144a8241fb2362f0b149f6ec`
- 修订21：`c0255967aff0abbdbd83156c846f930716468ffe1fd6dd0aeff91b6139d2ffc6`

## 核实的行为

三个独立来源都从真实XLSX的85%、fitToPage=true、fit2×3开始。公开Page Layout入口显示85和fit模式提示，拒绝9、401、12.5、空值；取消不写草稿。同85确认关闭fit，再次同85确认不改草稿。稳定sheetId下真实双击改名后仍读到85和已关闭的fit；公开Undo撤销此次改名后最终仅保存页面设置。

stale校验通过公开sheet-tab DOM Enter键事件模拟modal打开期间外部切表，先等Other的`aria-selected=true`，再确认原目标失效被拒绝，Scale仍为85。此事件直接调度绕过模态焦点限制，不是普通用户穿过modal操作，也没有注入工作簿/debug状态。

最终10/100/400分别经公开File→Print生成实际HTML，仅截获iframe.print避免系统窗口。刷新草稿以及明确打开保存后新修订，比例值、实际打印HTML分页及尺寸一致。源renderer有200%上限，本地既有renderer支持400%，此处保留并证明该已知差异。

每次保存operations只有一个`applyPageSetups`，目标仅Scale；使用项目真实Python `patch_office`生成bytes，再经HTTP下载核对SHA。openpyxl+lxml重新读取有效比例、fitfalse和默认属性清除。只移除目标worksheet的scale/fitToPage属性后，完整XML与来源一致；fit2×3、landscape、copies2、六边距、A1、F1公式保持，所有其它ZIP部件逐字节一致。

## 探针修正与既有窄测试

首次built停在stale步骤，日志 `/tmp/workbook-print-scale-built-initial-stale-probe.log`，证据 `/tmp/print-scale-built-3Df8dJ/`；尚无成功保存。失败HTML显示Scale仍选中，裸DOM click未触发组件实际切表，因而确认正常关闭。查阅Univer实际公开tab键盘处理后，将smoke改为Enter事件并等待真实选中再保留原拒绝断言，未改生产代码、未放松保存和打印检查。期间一次编辑命令因系统无`python`未生效，随即终止误启进程并用`python3`完成探针修改；没有产生保存。最终完整三个来源一次通过，成功后未重复测试。

已有窄测试记录只读取，不重复执行：

- `workbook-print-scale.test.ts`两项通过，记录在 `/tmp/workbook-print-scale-green.log`；该日志同轮旧Ribbon断言失败不能整体称绿。
- Ribbon单项最终通过：`/tmp/workbook-print-scale-ribbon-final-green.log`。
- main四项分两次通过：`/tmp/workbook-print-scale-main-final.log`含三项通过和rename旧默认false断言失败；按有效默认false修正探针后仅补跑rename，`/tmp/workbook-print-scale-rename-final-green.log`单项通过、其余三项跳过。

## 边界

这是独立打印百分比确认入口、草稿、真实补丁下载及浏览器打印HTML的窄验收。API授权与修订注册使用本地夹具；未证明生产HTTP授权、完整源即时修改PrintDialog、所有打印选项、打印机/PDF输出或桌面Excel视觉等价。本轮不重复既有fitToPage、打印区域/标题、Error Checking或完整测试，也未提交或push。
