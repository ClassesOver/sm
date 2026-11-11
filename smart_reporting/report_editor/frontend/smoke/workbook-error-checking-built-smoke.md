# XLSX Error Checking built 浏览器验收

```bash
node smart_reporting/report_editor/frontend/smoke/workbook-error-checking-built-smoke.mjs
```

默认独立端口4265，可设 `ERROR_CHECKING_SMOKE_PORT`。仅启动vite preview，绝不构建；须等待root最终统一dist放行。当前只完成Node语法、嵌入Python编译和真实openpyxl夹具生成/回读，**尚未执行built，不能宣称验收通过**。准备夹具 `/tmp/xlsx-error-checking-built-prepared.xlsx`。

真实XLSX有Protected、Editable、Other、Clean四表。前三表B2为`=1/0`，D4为无效`=#REF!`；Protected/Editable的F6跨表依赖Other!B2，Other的F6独立1/0。H8为文本`#REF!suffix`、I9为明确string类型`#FIELD!`、J10为明确string类型`=1/0`、远处Z220为文本`#REF!`。每张错误表应命中B2/D4/F6/I9/Z220五项，suffix与纯公式字符串不得误报。Clean虽有其它表错误仍应无命中。

公开Formulas→错误检查连续导航B2→D4→F6→I9→Z220→B2，严格row-major并回绕；反馈必须准确包含当前表数量/地址/值及当前计算结果说明，不接受读取失败伪称无错。每次检查官方名称框真实地址，并从Chromium截图提取真实canvas蓝色选择边框，远处目标必须实际可见；不注入debug/runtime、不通过产品内部API设置选区或值、不操作滚动DOM。

Protected受保护只读表允许导航。检查前后完整localStorage、保存状态、undo/redo及save enabled状态精确相等，零save请求，下载真实HTTP文件SHA与源相同。随后公开goto到Editable!B2并键盘修为7，等待官方计算后检查只剩四项，F6跨表错误仍存在；检查前后仅以用户这次编辑后的history/draft/status快照为基线，不能将错误检查自身写入历史。公开Undo恢复用户编辑后五错误重新出现。全流程save请求数为0，下载保持源SHA。当前不验证生产授权服务、Excel桌面等价、自动修公式、规则忽略或跨整簿扫描。

每case即时落盘cases.json与截图；失败保留failure.html/png及stage。成功result.json包含浏览器版本、源SHA、case反馈/截图SHA、每个实际加载JS的HTTP200与本地静态资源SHA、pageerror=[]、saveCount=0。授权/context路由为本地夹具，XLSX与下载走真实HTTP、真实产品built入口与官方计算/UI。无完整测试或旧专项重跑。


最终已通过：session47316 exit0，一次运行18 checkpoints、120实际JS HTTP200+本地SHA、saveCount0/pageErrors[]。产物 `/tmp/error-checking-built-HDMduP`，日志 `/tmp/workbook-error-checking-built-smoke.log`，总manifest `/tmp/workbook-error-checking-built-evidence.json`。root目视4-Z220.png确认远处真实选择与反馈/名称框一致；protected不变、当前表范围、修复后4项/Undo后5项及所有状态中立均通过。下载均为未保存源SHA，用户修复未发保存。最终资源身份及边界见 `../../NATIVE_XLSX_ERROR_CHECKING_ACCEPTANCE.md` 最终段落；上方“尚未执行”仅是准备阶段记录。
