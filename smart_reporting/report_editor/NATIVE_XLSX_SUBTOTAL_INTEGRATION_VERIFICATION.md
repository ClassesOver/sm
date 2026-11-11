# XLSX 分类汇总集成验证

日期：2026-11-10 至 2026-11-11。固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。源调查见 [分类汇总调查](NATIVE_XLSX_SUBTOTAL_INVESTIGATION.md)，保存及界面验证见 [专项验收](NATIVE_XLSX_SUBTOTAL_ACCEPTANCE.md) 和 [built smoke](frontend/smoke/workbook-subtotal-built-smoke.md)。本项不等于整个 Data tab 或全量 XLSX/Word 对齐完成。

## 实现

`workbook-subtotal.ts` 提供相邻分组计划及原生命令执行：选择首行为表头，一个分组列和一个值列，支持 sum/count/average、最多200个相邻组。计数使用 SUBTOTAL 3（非空计数），求和/平均值使用9/1。未排序的 A/B/A 保持三组，不隐式排序。最终坐标写组计/总计公式及粗体，明细level2、组计level1，summaryBelow=true。不会新造 OOXML subtotal writer。

对话框捕获 workbook/sheet 实际 core、选区、数据快照及 mutation revision。确认前后复核来源和权限；preflight 期间发生编辑时拒绝陈旧计划，保留用户的编辑。目标/列名通过 textContent 展示。取消、Escape、遮罩不改表；提交过程中拒绝关闭和重复提交，错误保留在面板可重试。

main 在首次原生修改前，以当前真实操作加所有候选插行、最终单元格和大纲调用既有文件引擎预演；迷你图及透视来源依赖提前拒绝。`subtotalPreflightOperations` 与真实结构日志按每次插行一个 operation 的粒度一致，整批遵守既有500项公开请求预算，避免成功修改后保存422。受保护、无法安全迁移的依赖、已有范围内行分组、SUBTOTAL公式或选中行含合并单元格等返回具体原因。

事务收集真实官方 undo/redo mutations，成功后一次登记历史；结构日志来自既有 mutation listener，绝不再将同一计划追加 staged。Undo/Redo 最后恢复对应 journal 与 outline 状态。事务内部暂缓草稿采集，成功后仅采集最终状态；失败还原 dirty/gridChanged/status，取消中间采集。预检期间不抑制用户编辑的采集。

失败回滚覆盖原生命令返回 false/抛错、基础 mutation 已执行但命令尚未登记 history、metadata 失败，以及 history push 执行前/后抛错。保留原 mutation.params 对象身份，避免破坏 CF/DV follower 的 WeakSet 授权。公开历史 API 没有恢复被清空 redo 的能力，因此有一处明确绑定 Univer **0.25.1** 的内部 stack 适配：只浅备份/还原当前 unit 的官方数组及元素身份；不建立另一套用户历史、不改其它 unit。升级 Univer 时必须重新验证此契约。

## 定向证据

- runtime 文件最终含17个专项向量；先前11项整文件通过，随后新增与相关回归分段通过，未为补日志重复完整文件。最终新增CF follower/历史push后抛错等4项日志：`/tmp/xlsx-subtotal-runtime-final.log`。CF测试使用真实插件与结构拦截器，在中途拒绝后恢复所有规则，且没有 unowned follower 拒绝。
- 对话框4项通过：`/tmp/xlsx-subtotal-dialog-green.log`；实现前缺模块 RED 保留 `...-red.log`。
- Ribbon 既有数据工具用例先 RED 后 GREEN，只执行该项（43跳过）：`/tmp/xlsx-subtotal-ribbon-{red,green}.log`。
- 500/501总数、逐插行粒度与协议字段通过：`/tmp/xlsx-subtotal-preflight-green.log`，实现前RED另留。
- 持久化3项及生产helper生成的6个实际XLSX，经 NativeDraft 恢复/retry、真实 Python native_office.patch_office 保存、ZIP CRC/lxml/openpyxl 独立回读通过。证据目录 `/tmp/xlsx-subtotal-acceptance/`；文件与公式缓存边界见专项验收。
- main真实插件集成9项分别取得GREEN：三聚合计算/单UndoRedo/草稿刷新与保存，取消、中途false、保护、迷你图/透视来源首mutation前拒绝，以及496项既有staged加候选超过预算时拒绝。首次夹具漏注册插件、错误pivot操作名均已修；这些失败不冒充生产故障。未为汇总计数重跑整文件。
- 首轮 `npx tsc --noEmit` exit0：`/tmp/xlsx-subtotal-typecheck.log`；首轮产品 `npx vite build` exit0/41.04s：`/tmp/xlsx-subtotal-build.log`。预算及其契约均exit0：`/tmp/xlsx-subtotal-budget.log`、`/tmp/xlsx-subtotal-budget-contract.log`。没有扩大预算，main237.0KiB（上限250），新增独立subtotal11.4KiB。

浏览器必须另以实际已加载构建身份、公开保存下载及新修订重开验证，最终状态以built文档为准。headless集成、公式字符串正确、构建hash各自不能替代完整浏览器功能证据。没有真实桌面Office验收，不宣称桌面渲染/计算完全等效。本轮未改发布签发链，未提交、推送或部署。

## 浏览器发现的问题与后续修复

首轮built三种聚合的计算、保存、下载、新修订重开都成功，但整体pageerror守卫失败，捕获4条“分类汇总期间工作簿已变化”。这轮不能标记浏览器通过。旧证据 `/tmp/xlsx-subtotal-acceptance/built/` 及首轮静态资源manifest留存；诊断 `/tmp/xlsx-subtotal-acceptance/diagnostic/page-error-1.json` 的stack明确指向docs-ui内嵌编辑器 `_pushHistory`。

临时收集历史的方法错误地拒绝其它unit。修复将非目标unit传给原官方bound push，并将partial逆向捕获限定目标unit；目标事务成功或回滚都不吞其它unit历史。真实双unit两个向量先RED后GREEN；6项相关窄回归通过，日志 `/tmp/xlsx-subtotal-runtime-foreign-{red,green}.log`。本次未清除pageerror、未静默忽略异常，也未将foreign记录并入目标Undo。

原先三个保存checkpoint不重复提交。修复后使用新来源revision身份（offset30）及独立built-final目录重新验收创建过程，旧文件只用于留存/回读。最终结果以built文档为准。


## foreign unit 修复后的冻结构建

`npm run build`（含 tsc --noEmit 与 Vite）exit0，Vite40.89s，日志 `/tmp/xlsx-subtotal-foreign-fix-build.log`。新产物预算和预算契约均exit0，日志 `/tmp/xlsx-subtotal-foreign-fix-budget.log`、`/tmp/xlsx-subtotal-foreign-fix-budget-contract.log`。main237.0KiB、subtotal11.4KiB，未扩大250KiB主入口上限。

冻结subtotal产物 `lazy-workbook-subtotal-CGr6pzRh.js`，SHA256 `2444d53f88a838921894fdc2b1e52b3e353b2506626e58807c867e21f632b05f`。构建通过不替代浏览器创建过程验收；新修订31/40/50的独立验收目录为 `/tmp/xlsx-subtotal-acceptance/built-final/`。


最终 `/tmp/xlsx-subtotal-acceptance/built-final/summary.json`：ok=true、3case、125已加载JS均HTTP200+SHA、errors=[]，Chromium140.0.7339.16。新来源31→32、40→41、50→51各一次保存，sum100/count4/average25，均覆盖真实入口、单次UndoRedo、草稿刷新、真实Python native patch、实际HTTP下载、独立ZIP/lxml/openpyxl及明确新修订重开。root独立读取summary、逐份下载SHA与125资源实际静态文件SHA核对通过，目视sum-reopened.png确认30/70/100、大纲和Tail正常。首轮失败证据不撤销、不覆盖。文件公式cache仍为null，不宣称桌面Excel重算通过；认证/修订路由为fixture，不代表生产鉴权或打印等效。
