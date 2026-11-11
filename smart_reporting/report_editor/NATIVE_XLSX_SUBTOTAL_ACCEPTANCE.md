# 原生 XLSX 分类汇总专项验收

日期：2026-11-10。此文档记录本地实现证据及边界；固定源调查见 `NATIVE_XLSX_SUBTOTAL_INVESTIGATION.md`。

## 保存与草稿约束

分类汇总通过既有 `applyRowColumnOps`、`applyCellEdits`、`applySheetOutline` 保存，不新增私有 OOXML writer 或 server operation。结构操作按执行顺序、单元格编辑使用最终坐标；`summaryBelow: true` 必须显式保存。

`NativeDraft` 绑定作用域、文档、修订和源 SHA-256，JSON 保存完整 operation 列表。主视图恢复时从不可变 `original` 重放一次，将恢复的列表保留为 staged，清空结构日志，并把重放结果作为新差分基线。确认分类汇总时不能既将插行计划加入 staged，又让原生 mutation 重复进入 structural。恢复后再次保存应沿用同一列表，不能重新应用计划到已汇总文件。

## 验收证据

验收探针保存在 `/tmp/xlsx-subtotal-acceptance/`。`fixture.py` 生成 A1 和 C5 两种选区来源，包含两组明细、表后 Tail/99/keep、跨表绝对引用及范围公式、Body 定义名称，并预设 `summaryBelow=false`。`readback.py` 使用独立 `zipfile` CRC、lxml 和 openpyxl 读回，不用生产 reader 自证。

已执行真实生产 `planSubtotal` + `subtotalPreflightOperations` → `NativeDraft` JSON 恢复及同一 request 重试 → Python `native_office.patch_office` → 既有 Node bridge 保存。`sum/count/average × A1/C5` 共六份实际 XLSX 均通过独立回读：

- 汇总公式分别使用函数号 9、3、1，组计和总计最终坐标正确；六个汇总标签/公式格均加粗。
- 大纲级别为 `[0,2,2,1,2,2,1,0,0]`，无意外隐藏/折叠；`summaryBelow=false` 输入明确改为 `true`。
- Tail/99/keep 完整移至第 9 行或第 13 行，跨表绝对引用、范围公式及 Body 定义名称正确迁移。
- ZIP CRC 全通过，结果见 `readback.json`，文件 SHA-256 见 `SHA256SUMS`。六份文件的总计计算缓存均为 null，未将公式文本正确当作缓存已计算。

临时复现：运行 `fixture.py`，`node build.mjs`，`node probe.mjs`，以项目根目录 `PYTHONPATH` 运行 `save.py`，再运行 `readback.py`。所有脚本及文件均位于上述临时目录；bundle 仅针对探针，未改公共 dist。

仓库专项测试：`frontend/src/workbook-subtotal-persistence.test.ts` 的三项通过；使用真实 planner，经既有 bridge 保存，覆盖 C5 三聚合、草稿恢复与保存身份不变、重复重放从同一 original 得到相同模型、新修订不恢复旧操作。主视图 `workbook-main-subtotal.test.ts` 九项均取得通过证据：首轮七项通过，修正测试 pivot fixture 的操作名后 pivot 单项通过，随后新增预算单项通过。使用真实 Univer sheets/formula/note/DV/table/CF 插件，保留正式主视图、对话框、NativeDraft、native transport 与 bridge；只替换渲染宿主和 Ribbon 挂载以捕获用户命令。

三聚合会话内总计分别为 100、4、25；一次 Undo 恢复所有明细、空大纲及空草稿，Redo 重现公式与结构；刷新后保存仅含三次插行，尾行、跨表绝对引用及 Body 名称正常。取消、第二次插行返回 false、受保护表、既有迷你图、真实透视来源、496 条既有 staged 操作加分类汇总超过 500 条预算，都验证零新增草稿/历史或首条插行前拒绝。测试夹具初次缺少 DV 插件注册，按当前宿主依赖补齐；未通过临时禁用生产代码制造 RED。

构建浏览器 smoke 脚本为 `frontend/smoke/workbook-subtotal-built-smoke.mjs`；首次正式构建执行已取得三聚合 100/4/25、取消、Undo/Redo、草稿刷新、下载及新修订显式重开证据（`/tmp/xlsx-subtotal-acceptance/built/`）。但最终捕获四个“分类汇总期间工作簿已变化” pageerror，故整体尚未通过。保存前诊断捕获 `docs-ui._pushHistory` 完整栈，证实全局 history 拦截误拒其它编辑器 unit；诊断没有调用保存。实现方修复为将其它 unit 的历史委托官方服务，同时将 partial rollback observer 限定为当前 unit；真实双 unit 专项回归通过后重新构建。旧失败来源和诊断保留，重测采用新来源 31、40、50，各只保存一次。

最终浏览器验收 **通过**：`SUBTOTAL_SMOKE_REVISION_OFFSET=30 SUBTOTAL_SMOKE_DIRECTORY=/tmp/xlsx-subtotal-acceptance/built-final node smoke/workbook-subtotal-built-smoke.mjs`，exit 0；Chromium 140.0.7339.16。`summary.json` 记录 `ok=true`、`errors=[]`、`saveCount=3`、`resourceCount=125`。125 个加载 JS 全部 HTTP 200 且与本地构建 SHA-256 一致，新 subtotal chunk 为 `lazy-workbook-subtotal-CGr6pzRh.js`，SHA-256 `2444d53f88a838921894fdc2b1e52b3e353b2506626e58807c867e21f632b05f`。

| 聚合 | 来源→新修订 | 选区 | 浏览器重算 | 实际下载 SHA-256 |
| --- | --- | --- | --- | --- |
| sum | 31→32 | Sum Data!A1:B5 | 100 | `f17aa1197398e9ab60b9906155aaa8b67dafa122bc2c0d56329908c5b95c6021` |
| count | 40→41 | Count 数据!C5:D9 | 4 | `9d5fcbd58d665e88b09093ff5fd1937352e050ee41d146b87ae550294499ef20` |
| average | 50→51 | Average's Data!C5:D9 | 25 | `4b254b4f033c73cc06136a21c95fe2a0579c2ad76f6d1c1c789065fbc003ad7d` |

三种聚合均通过真实 Ribbon/Go To/对话框及原生剪贴板读取计算值，取消零草稿、一次 Undo/Redo、草稿刷新、保存下载、新修订显式重开全部通过。保存端为 smoke 本地 HTTP fixture，真实调用 Python `native_office.patch_office`；未宣称连接生产数据库修订服务。下载文件均由独立 ZIP/lxml/openpyxl 读回公式、六格粗体、大纲、summaryBelow、Tail、跨表公式及 Body 名称，缓存仍为 null。截图已目视检查对话框字段和新修订汇总表。

完整证据位于 `/tmp/xlsx-subtotal-acceptance/built-final/`：`summary.json`、`assets.json`、`build-manifest.json`、`saved-source-{31,40,50}.json`、`downloaded-{32,41,51}.xlsx`、`{sum,count,average}-{dialog,reopened}.png`。旧失败 run `/built/` 及无保存诊断 `/diagnostic/` 未覆盖。

## 证据边界

公式文本、样式与 outline 的文件读回不等于 Excel 桌面计算或浏览器交互验收。公式缓存与会话内重算分别报告；没有桌面验证时不宣称已完成。没有变更发布或导出签发链，不以本专项替代发布非阻断回归。
