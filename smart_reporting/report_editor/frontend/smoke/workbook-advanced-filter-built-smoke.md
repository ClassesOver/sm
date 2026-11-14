# XLSX 高级筛选 built smoke

等待 root 确认唯一构建完成后，在 frontend 运行：

```sh
ADVANCED_FILTER_SMOKE_DIRECTORY=/tmp/xlsx-advanced-filter-built-20261111-final-03 node smoke/workbook-advanced-filter-built-smoke.mjs
```

固定源语义是单列 1–2 个自定义条件、AND/OR；不是 Excel 条件区域、复制结果或 unique。

脚本只通过公开 GoTo、Data Ribbon、对话框、Undo/Redo、保存和下载 UI 编辑。三个场景分别覆盖：已有筛选 AND/C5 偏移与保留另一列条件；无筛选确认创建与 OR；文本 equal 省略 operator、已有筛选与手动隐藏。每场景检查取消草稿零变化、一次 Undo/Redo、reload 恢复、保存、实际下载、明确打开新修订。新增重开身份诊断要求打开新修订时 status 为已保存且本地操作草稿为空；AND 场景随后更改条件并 Undo，严格要求该新修订草稿恢复空操作、标签“已保存”、精确复制 10；Redo 必须恢复同一条件草稿与“有未保存修改”、精确复制 5；再次 Undo 必须完全恢复第一次 Undo 草稿与已保存状态。保存调用真实 Python native_office.patch_office；实际下载文件通过 ZIP CRC、lxml 全 XML 和 openpyxl 独立核对条件、行可见性及数据保全。不能将 localStorage 表达式检查单独当作画布可见性证据。

所有实际 JS response 与磁盘 SHA256 比对，复制构建 manifest，捕获 pageerror。每次成功保存即写来源回执与文件；同一目录续跑跳过已完成保存，缺回执孤立产物则停止，防止重复签发。可用 ADVANCED_FILTER_SMOKE_CASE=and/or-create/text-equal-manual 只跑未完成场景。脚本不自行构建。2026-11-11 冻结构建上的三个基础场景曾完整通过；追加身份/草稿诊断后，AND 新修订修改条件并 Undo 仍留有 outline 操作，严格空操作等待失败。final-01 目录的旧 summary 属于之前完整轮次，不能作为追加诊断通过证据；当时要求修复并重新构建后使用新目录验收，最终结果见下文 final-03。

本地模拟 HTTP 仅提供原生 context/file/save/download 边界；不代表真实数据库修订注册或完整服务器 HTTP 部署验收。未执行的浏览器场景不得记通过。


## 2026-11-11 最终证据

`final-01` 在追加新修订 Undo 诊断后暴露 outline 伪差分，旧 summary 不代表追加诊断通过。`final-02` 在 outline 修复后通过空草稿与可见行检查，但 Undo 标签仍错误显示未保存，不能作为标签修复证据。二者保留原目录与回执，没有重复保存成功来源。

剪贴板等待的真实根因已查明：当前 Playwright `waitForFunction` 不 await async predicate，Promise 直接为 truthy；脚本改为 Node 侧逐次 await `clipboard.readText()`、10 秒有界严格等值轮询。每次只发送一次公开 Ctrl+C，无重复复制、无宽松匹配、无清 localStorage。最终轮使用该实现。

root 确认 `/tmp/four-format-build-final3-20261111.log` 的 session83592 exit 0 并冻结 manifest 后，session13810 在全新 `/tmp/xlsx-advanced-filter-built-20261111-final-03` exit 0。实际 summary 为 `ok:true`、三场景、`saveCount:3`、126 个 JS、`errors:[]`、浏览器 `140.0.7339.16`。manifest SHA256 为 `184c94a96f863198c30ffcfaae1ec2169a8e6b6df2eaca50415bbd62538eada5`，所有资源 response 均与磁盘 SHA256 一致。

三场景新修订身份/已保存/空草稿、取消零修改、Undo/Redo、刷新草稿、唯一保存、真实下载与独立 ZIP/XML/openpyxl 回读全部通过；三 receipt 操作均只有 `applySheetFilter`，全表数据不变。AND 额外改条件→Undo→Redo→再次 Undo 的状态、完整草稿与精确复制 5/10 也全部通过。三张 `*-reopened.png` 已实际查看。具体 SHA256、回执和范围边界见 `../../NATIVE_XLSX_ADVANCED_FILTER_ACCEPTANCE.md` 与 checkpoint 的 `summary.json`。没有改生产代码、没有自行构建、没有全套测试或提交。

## 2026-11-12 PC 窗口续批

PC模式复用五视口布局/键盘检查，保留真实引擎、保存/下载/重开；额外fixture包含数字格式、批注、超链接、合并区和另一张工作表，独立回读必须证明仅筛选定义及行可见性变化。此模式禁止普通重放已有保存回执，须使用全新目录并锁定构建manifest：

```sh
TMPDIR=/dev/shm ADVANCED_FILTER_PC_LAYOUT=1 \
ADVANCED_FILTER_SMOKE_CASE=or-create \
ADVANCED_FILTER_EXPECTED_MANIFEST_SHA256=2f3d5846cbb6cdf122d35c250655707e7813b234e89c3634b1b6b1574b51162f \
ADVANCED_FILTER_SMOKE_DIRECTORY=/dev/shm/advanced-filter-new-run \
node smoke/workbook-advanced-filter-built-smoke.mjs
```

该SHA只指本批冻结静态构建，当前源码后续并行变更不由本轮运行证据背书。`ADVANCED_FILTER_REVIEW_ONLY=1` 用于已保存文件的只读复核，必须预先提供相同manifest、source、revision和saved-source回执；save路由强制拒绝调用，仍执行浏览器下载、独立回读及重开检查。它不能证明原保存应答中的告警展示。

最终成功目录为 `/dev/shm/office-xlsx-advanced-filter-and-review-final-20261112`（既有AND文件，只读、0保存）、`...-or-built-20261112`、`...-text-built-20261112`（后两者各1保存）；首次AND实际保存留在 `...-built-20261112`，保存后因夹具issues格式错误停止，该失败目录未再次签发。全批真实保存3次。中间只读复核因5.00显示值预期错误停止后，改用精确显示字符串，未更改源数字格式。

25个成功生产布局场景、275条Tab记录、171个资源SHA、三个独立文件保真回读通过；AND改条件后Undo/Redo及回到空草稿/已保存精确检查通过。6种故意损坏均被独立校验器拒绝，普通重放保护经32个证据文件前后SHA验证。首轮AND初始/空错误10个布局场景只作为阶段证据，不计入25。组件忙碌/长错误等20场景另由 `office-xlsx-advanced-filter-component-smoke.mjs` 验证，回调为可释放Promise，不代替引擎验收。详见 `../../NATIVE_OFFICE_UI_AUDIT_20261112.md` 的“XLSX 高级筛选窗口 PC 续批”。
