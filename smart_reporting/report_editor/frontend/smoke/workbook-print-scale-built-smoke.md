# XLSX 打印百分比 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/workbook-print-scale-built-smoke.mjs
```

独立默认4271端口，`PRINT_SCALE_SMOKE_PORT`可覆盖。仅启动vite preview，不build。2026-11-10 在 root 统一 build、预算和契约通过后的冻结产物运行，exit0；详情见 [验收记录](../../NATIVE_XLSX_PRINT_SCALE_ACCEPTANCE.md)。

三个独立来源revision1/10/20均含Scale与Other，真实scale85、fitToPage=true、fit2×3、landscape、copies2、A4、自定义六边距、30pt首行及公式。三次有意义保存分别最终10/100/400，不重复fit全套。每来源先核对85和fit模式提示，拒9/401/12.5/空值，取消不写；确认同85关闭fit，二次同85确认noop。独立本地确认式modal仅对应固定源PrintDialog百分比子功能，不声称完整源即时打印dialog等价。

stale边界通过公开sheet-tab DOM Enter键事件在modal打开期间模拟外部切表，确认拒绝且原85不改；**该事件绕过模态遮罩的用户焦点限制，不是用户实际点击路径**，不注入工作簿/debug状态。真实双击工作表改名后再次打开须沿稳定sheetId读取85和已有fitfalse，随后公开Undo改名恢复Scale，最终只保存applyPageSetups。该Undo针对rename，不声称独立page setup journal已有百分比Undo/Redo契约。

最终比例通过公开File→Print生成实际HTML（仅截获iframe.print阻止系统窗口），核对30pt行分别3/30/120pt，保留HTML证据；刷新草稿及明确新修订重开须值和实际打印HTML分页/尺寸一致。源允许保存400但其renderer clamp200；本地沿既有10–400分页支持，不照抄源200bug。此处只验实际浏览器打印HTML，不宣称打印机/PDF输出或桌面Excel等价。

保存调用项目真实Python patch_office，operation只一个applyPageSetups。真实HTTP下载SHA匹配保存bytes，openpyxl+lxml核对scale/fitfalse；100须移除默认scale属性，fitfalse接受缺省/0/false。只mask worksheet直属scale/fitToPage属性后完整目标XML一致，fit2×3、copies、orientation、边距、内容/公式及所有其它ZIP部件原字节。API授权为本地夹具，不声称生产授权集成。

逐来源完成即保存result/download、截图和日志；`PRINT_SCALE_RESUME_DIRECTORY`读取前次result并核验下载SHA后跳过已过保存，`PRINT_SCALE_START_REVISION`仅指定后续来源；失败留failure.html/png/stage。全部加载JS必须HTTP200且本地SHA相同，console/pageerror为空。本轮最终三个来源全部通过，3次保存，真实打印HTML页数1/1/8、首行高3/30/120pt。日志 `/tmp/workbook-print-scale-built.log`，产物 `/tmp/print-scale-built-5hZxNX/`；未复跑旧专项或完整测试。
