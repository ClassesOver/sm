# XLSX Ribbon 删除图表与合并工作簿专项

日期：2026-11-13。证据根：`/dev/shm/office-next-xlsx-ribbon-commands-20261113`。

## 固定源与范围

固定源为 `/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。源 `ExcelShell.tsx:2280` 提供 `chart-delete` 按钮，`3119` 提供 `merge-workbooks` 按钮，`ribbon-actions.ts:392/1913` 分别接源删除与合并处理。

本地这两项已有宿主处理和原生 operation，但 Ribbon action 漏传 command，被渲染为永久 disabled。本次仅补真实入口与入口接通后暴露的必要合并宿主问题；没有新增引擎、保存协议、Python endpoint 或合并算法。

产品只改 `frontend/src/workbook-ribbon.ts` 与 `workbook-main.ts`。测试只改 `workbook-ribbon.test.ts`、`workbook-main-calculation.test.ts`。`workbook-merge.ts` 和工作簿桥 `bridge/operations.ts` 与起点身份完全相同。

## 最小修复

- Ribbon 为两项 action 补入既有 command。
- 合并选择器使用 `getActiveWorkbook().getWorkbook()` 的稳定内核身份，避免每次重新取得 facade 导致打开即判定草稿变化。
- 合并提交持有自己的 `inert` 锁时，不用该锁否定自身提交；加载、失败状态、保存、关闭、计算、结构保护及祖先锁仍须复核。未泛改全局 `editable()`。
- 成功合并复用 NativeDraft 的 before/staged 历史；完整重建后不再用 `markDirty()` 把撤销送往已清空的 Univer 历史。

## 定向 RED → GREEN

- `ribbon-red.log`：两项真实 Ribbon 按钮在可编辑状态仍 disabled，2 项明确行为 RED。
- `ribbon-green.log`：2 项真实按钮点击分派既有 command，通过；只读时不分派。
- `host-green-initial.log`：删除图表的真实 Ribbon、原生草稿、人工网格内容和 Ribbon Undo/Redo 专项通过。其同批合并测试仍失败，不能称整文件全绿。
- `merge-host-diagnostic.log`：真实合并入口显示“当前工作簿或草稿已变化”，选择器即时销毁，确认 facade 身份比较问题。
- `merge-stable-identity.log`：修复稳定身份后选择器可打开与取消；提交仍无法登记新增工作表。合并事务内部的 validate 受自身 inert 锁否定，随后仅在该事务内收敛锁判断。
- `merge-own-lock.log`：合并成功后点击 Undo 仍为 2 个工作表，确认现有历史路径问题。
- `merge-save-settled.log`：取消不改草稿、真实文件读取与合并、保留人工数据、Ribbon Undo/Redo、同身份 NativeDraft 重开及一次真实引擎保存全部通过，1 项宿主专项。前一次 `merge-host-green.log` 在最终保存的默认 1 秒等待上超时；仅增加该测试等待到 10 秒后通过，没有为此修改产品。

前端 `tsc --noEmit` 执行一次，exit 2：日志为并发 Word/PDF 文件的类型错误与依赖缺失，没有本批 XLSX 文件错误。不得描述为全前端类型检查通过；统一冻结构建需以主代理最终结果为准。目标文件 `git diff --check` 通过。

## 能力边界

删除复用本地 `applyChartDeletions` 及目标身份/保护/关系守卫，不代表任意 shape/image/未知 drawing 删除或源 `applyVisualEdits` 的完整迁移。

合并继续是已有追加工作表的值、逻辑格式、列宽、行高和合并区域导入。公式只导入可信缓存计算值，不保留原公式引用图；缺失或不可信缓存仍拒绝导入。不能称完整 OOXML 包、图表、图片、透视表、宏或连接迁移。本次没有扩大这些能力。

## 统一冻结 HTTP 验收

统一冻结根为 `/dev/shm/office-next-page-borders-ribbon-master-fill-detect-20261113`。主代理修复一行纯类型后类型检查 exit 0，并验证对应 esbuild JS 前后字节相同；Vite、预算、四桥及脚本语法检查通过。静态 manifest SHA-256 为 `5ede4bf0e2689e7427f0e90ea296a912ae56aa4ef124be01a1916d8af55c3c90`，工作簿桥为 `ed85b3d46f2995a79457c0f71d3106918d0c5222f2ddbce432e09e9f6ba530ea`。本代理没有重建共享产物。

`browser-frozen-01` 是唯一完整 HTTP 保存运行，exit 0：

- 真实 Ribbon 明确选择第二张同名图、删除、删除 Undo/Redo、合并取消、合并文件、保留人工 J2 bold、合并 Undo/Redo、刷新恢复、保存下载和新修订重开均通过。
- `r4 → r5`，`savedRevisions = 1`，`plannerCalls = 0`，没有重复保存。
- 274 份 JS/CSS 响应逐一与冻结磁盘 SHA 相同。浏览器错误、console error、HTTP error 和资源身份错误均为空。
- 下载 7,186 字节，SHA-256 `0aacda563834507689207d7ee630b63386bfa0cac343d813a81049e066789b2a`。独立 openpyxl/lxml/ZIP 验证 `ok: true`：第二图部件已删除，第一图 XML 与首锚点 C14N 精确一致；人工 J2 bold 和原数据保留；`Data (2)` 的值、bold/fill、列宽、行高、合并区域正确；来源公式 `=6*2` 作为可信缓存字面值 12 导入，没有伪称保留公式。
- `validation.ok = false`，具体原因 `native_source_review_pending`；下载照常签发。没有将业务事实或完整版式标为验收通过。
- 105 份实际 live 后端起止身份完全相同。相对于本轮冻结基线有两项已存在差异：`native_pdf_contract.py` 从 `de4b206f…` 变为 `8fe8eef7…`，`delivery/docx_native.py` 从 `28a07f30…` 变为 `1f100ad6…`。完整身份保存在 `backend-start-identities.json`、`backend-end-identities.json`、`backend-baseline-mismatches.json`，不能称后端完全隔离或与冻结基线完全相同。
- 已目视检查合并后的桌面截图与修订重开后的图表说明：合并按钮可用、人工 bold 与两个工作表标签可见，图表说明只列第一张 North 图。

实际脚本 `frontend/smoke/workbook-ribbon-commands-smoke.mjs` 在运行前保存了 runner、独立验证器、服务与辅助脚本字节及 SHA。实际 runner SHA-256 为 `3eafe262f19eaf654cf3f2817f8927be466701aed349e05a792b5b6482e38bbe`，独立验证器为 `52090ff2dc9794b7b38b8683c69ae1b6e790bb42aa5b533cd11a37e4fa77dfbe`。

冻结复制期间命中了仅 smoke 脚本变化的守卫，主代理保留了失败与 `COPY-HARNESS-DRIFT-RECONCILIATION.json`，没有重置产品源码快照。冻结旧 runner 为 `4fe9e20f8e64a331118629ee79badb2d188201bd90e5fa2e0760250bb62e87f2`，不能冒称为实际执行版本。实际运行使用最新 live runner；后续变化仅为精确使用 `FileChooser.element()` 定位取消输入，以及去掉硬编码后端数量提示并动态记录 `backendCount`。本次运行目录的 `harness-freeze-reconciliation.json` 明确记录旧版与实际副本差异，没有因脚本差异重建或重新保存。

本批 ready 后 `workbook-main.ts` 还发生了其它会话的格式单元格接线变化。主代理冻结当前 live 文件，本代理没有用旧 main 整文件覆盖；本代理负责的 merge 分支单独保存在 `owned-main-block.json`，避免把并发内容冒称为本次修改。
