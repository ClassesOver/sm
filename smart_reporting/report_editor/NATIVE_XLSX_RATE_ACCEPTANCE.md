# XLSX RATE 数值覆盖验收

固定来源为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/sheets/src/renderer/rate-function.ts`，SHA256 `54c2913024019669633255dc057db9d05d0dd229fe3a0daa6c118430cf8f877b`；源测试 `apps/sheets/tests/rate-function.test.ts` SHA256 `55380f536bdf9070bc60db9f0a2312accfe451aa1066aa6ea3fa900adde3079a`。沿用项目现有 GenOffice Apache-2.0 LICENSE/NOTICE。本地文件 `frontend/src/workbook-function-rate.ts` 和对应 `.test.ts`。

## 源语义与最小适配

求根扫描点、残差公式、二分迭代及继承内置 RATE 的实现保持源代码。内置 `calculate` 处理默认值、字符串数值转换、参数错误、数组广播、type 标准化及合法性校验；只在内置 `_getResult` 返回 `#NUM!` 时使用源二分后备。正常内置结果及非 NUM 错误原样返回，不替换公式计算体系。

安装 API 为 `installRateFallback(runtime: Pick<UniverRuntime, 'univer'>): { dispose(): void }`。root 应在首个 loadWorkbookData 后同步安装，再在 loading=true 期间统一 calculation.calculateNow，宿主释放时先 dispose 后关闭 Univer。复用源同步注册和 0ms 重绑以抵抗首次工作簿初始化覆盖；本地增加无 provider no-op，timer 仅在当前 executor 是捕获 original 或原生 RATE 构造类时重绑；第三方后续 owner 保留。dispose 幂等并清除 timer，仅当前仍为自身 executor 时恢复 original，original 不存在则注销自身，不影响后续 owner。启动期重绑不主动触发重新计算，沿用源时序；异步首个工作簿直接创建的公式计算已经用真实测试验证，但真实 main 含异步 readWorkbook 时 timer 可早于 plugin ready，故宿主集成采用明确的加载后安装加统一强制计算。

## 真实 RED / GREEN

当前 Univer 0.25.1 已优化 pmt=0 的直接增长率计算，源样例 `RATE(5,0,-100,0.0001)` 和源默认 guess 样例 `RATE(5,-10,-100,10.0000001)` 在原生引擎均已是数字，不能冒充当前缺口。

实际反例为工作表单元格公式 `=RATE(5,-100,100,10)`：未安装时真实 Univer 计算返回 `#NUM!`，测试因期望 number 而失败（`/tmp/function-rate-engine-real-red.log`）；安装后为 `0.9623255039434997`，金融方程残差绝对值小于 `1e-8`（`/tmp/function-rate-engine-green.log`）。0ms 重绑缺失时，首个工作簿初始化覆盖 executor，前置安装测试失败（`/tmp/function-rate-early-red.log`）；复用源 timer 后通过（`/tmp/function-rate-early-timer-green.log`）。

定向验证先 7/7 通过（`/tmp/function-rate-final-green.log`）：真实单元格计算、首个工作簿前安装、普通/错误/数组结果与内置逐值一致、headless no-op、dispose/timer、后续 owner、original 缺失的注销。随后仅新增 2 项 2/2 通过（`/tmp/function-rate-preview-array-green.log`）：native executeFormulas 预览与单元格同值、引用参数、显式极端 guess 的深负根、救援后的数组溢出、源无根与深负边界。未运行完整测试或构建/改写 static。本模块最后 tsc 未报错；当次全项目 tsc 仅因 root 正在新增的 main-calculation 测试 formula cell 缺 value 而失败（/tmp/function-rate-typecheck-final.log），不能据此声明全项目类型检查通过。

## 数值边界与剩余限制

后备扫描域沿用源：最接近 -1 的点为 `-1+1e-12`，上界 `1e9`；最多二分 200 次。跳过非有限残差并中断该扫描段，不保证范围外或比下界更靠近 -1 的根。它寻找第一个已扫描异号区间的根，不保证多根问题中与 guess 最近的根；同号区间中无符号变化的切根可能被漏过。只有内置明确返回 NUM 才后备；内置若返回数值但残差不良，不额外修正。源残差 near-zero 分支和原始浮点数运算均保留，不宣称任意规模/病态金融方程与 Excel 完全一致。依赖当前内置 RATE 的 `_getResult` 扩展点，未来版本不存在该方法时不安装后备。

本批提供函数模块，main 安装和真实产物 GUI 集成由 root 后续验证；本记录不把未完成集成标成已交付。

## 主入口与真实浏览器补证

root 在首个 loadWorkbookData 后安装三项数值覆盖，并于 loading 期间 calculation.calculateNow；真实 main 初载四值正确且 draft.operations 为空、save 未调用（`/tmp/workbook-functions-main-final-green.log`）。

新增独立 `frontend/smoke/workbook-function-values-gui-smoke.mjs` 首跑通过（`/tmp/function-values-gui-first.log`，未重复跑旧函数对话框全流程）：初载 CELL 中文/空格/%路径，RATE 默认guess反例，显式 `_xlfn.MINIFS/MAXIFS`；真实 canvas pointer 与键盘将 A1 从 5 改到 10，RATE 从 `0.962325503943` 变 `0.998920069612`，原 SUM 从 8 变13；草稿刷新恢复；真实 Python patch_office 保存，新 XLSX 经 openpyxl 回读全部原公式/marker与 B2 文本保留，恰一条单元格编辑；修订2重开数值正确，pageErrors 为空。该验证是 dev 浏览器宿主，尚未替代最终静态构建验证。

## 最终静态产物验收

`/tmp/function-values-gui-built-event-lock-final.log` 终态 exit0、ok=true、pageErrors=[]。实际 preview 静态产物使用原生 namebox 首次选择验证 Rendered 后 si 控制器无异常；后续使用 Ribbon 定位交还官方焦点，真实键盘输入 A1=10，Ctrl+C、草稿刷新、真实 Python patch/openpyxl 及修订2重开均通过。未使用 dev runtime globals 或 JS 源码拦截。288 次实际 JS 响应均为 HTTP200，响应 SHA 与冻结 static 文件逐一一致，包括 main/engine/数值函数/future-functions/navigation。

原始 TSV 初值为 `5\t报表/[运营 %.xlsx]Values\t0.962325503943\t0\t0\t8`；修改并重开后为 `10\t报表/[运营 %.xlsx]Values\t0.998920069612\t0\t0\t13`。每次复制前写唯一 pending-proof 标记，原生复制异步过程中曾出现 wait 返回后再次 read 仍为标记的波动，数值检查拒绝标记并继续复制，最终上述新 TSV、实际保存文件、修订重开全部通过；不能把这一证据宣称无瞬态剪贴板时序问题。TSV 数值为 12 位小数展示，残差验收阈值 1e-5，不冒充底层 IEEE 完整精度或完整表格像素验收。

关键产物 SHA256：

- `lazy-workbook-main-TIDMCHtw.js`：`03ab2ecc62b0da835c8c5e5b321642afb4d0491232a71668e449939c96073d08`
- `lazy-workbook-engine-ALYWZ5G-.js`：`fc4e710fd36e5e1ed460e433a8eaf014a30741d327c4f49ea01ee3d67aa3e57f`
- `lazy-workbook-future-functions-hD9e7sTM.js`：`e6d83cff860ab666bd4d3c884f939d727382735c38febf9d8fff1cf237d7ee84`
- `lazy-workbook-insert-function-FBE3MIvK.js`：`300983f4055f527f5eb6e1447c044fb846ba7b08c6324ae8d8a5e1fe44676462`
- `lazy-workbook-insert-function-Dhsfi0gc.js`：`940db4f866bc509613c810ec25f70d52194012e84ec8c14d9e02b232fb57a513`
- `lazy-workbook-navigation-DXYENm6r.js`：`d32f26fd9551f42134c56ed644efa2079676547ffc8ab72f707bb29330dfa239`

原先真实 namebox 的 si 异常日志保留 `/tmp/function-values-gui-built-native-namebox.log`；确认为公开 ready 早于 Univer Rendered。新增 inert 暂锁曾破坏 native 输入初始化，窄唯一变量对照保留 `/tmp/workbook-goto-no-inert-probe.log`；最终事件锁保留 focus 初始化、阻止忙期用户输入，并在官方 Rendered 后公布 ready，窄真实命令与 A1=10 证据在 `/tmp/workbook-goto-event-lock-direct-probe.log`。不忽略 pageerror，也未用任意 sleep 作为产品修复。
