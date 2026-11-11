# XLSX 高级筛选验收

日期：2026-11-11；固定 GenOffice `/home/junge/pros/genoffice-source-full` ref `f8c17004fb730df11f0f743164ffd8b4281bb38c`。范围是单列一至两个自定义条件、AND/OR，保留其它列条件和原位数据；不含 Excel Advanced Filter 条件区域、复制结果或唯一记录。

## 主视图及实际保存证据

测试 `frontend/src/workbook-main-advanced-filter.test.ts` 使用真实主视图、真实官方 `UniverSheetsFilterPlugin`、真实 `NativeDraft` 和保存 transport；只替换 DOM 渲染层和 Ribbon 挂载，测试调用实际 main 的 Ribbon callback。不能把它计作浏览器完整渲染验收。

- `/tmp/advanced-filter-main-red.log`：接线前已有/无筛选两条 cancel 测试均因 `filter-advanced` 未打开对话框失败，证明 RED 来自缺失实现。
- `/tmp/advanced-filter-main-green2.log`：取消两条、AND、无筛选确认创建及一次撤销/重做、原生命令拒绝、保护共六条通过。OR/文本失败暴露 `customs.and: undefined` 被 NativeDraft strict JSON 拒绝，未用放宽校验或延时掩盖。
- `/tmp/advanced-filter-main-or-text.log`：附加具体 feedback 定位上述错误。
- `/tmp/advanced-filter-main-remaining.log`：修复投影后仅补跑 OR、文本 equal、dateGroups、手动隐藏保留、Table 文件预检五条，全部通过。
- `/tmp/advanced-filter-main-boundaries.log`：stale 选区及 500 条已有操作预算两条通过；dateGroups 原测试错误要求 DOM 不存在，已修为隐藏状态并在 remaining 中通过。

AND/OR/文本的 main 保存回调实际调用仓库 `.venv/bin/python` 的 `native_office.patch_office`，未剥离 `hiddenRows` 字段。返回文件独立通过 ZIP CRC、lxml 全 XML 解析及 openpyxl 核对：`C5:E9`、相对 colId、AND 属性、OR 省略属性、文本 equal 省略 operator、另一列已有 values 条件、精确隐藏行、表头可见、尾行不变及全部单元格值一致；草稿重开、一次 Undo/Redo、一次保存操作集也被核对。这里不代表实际 HTTP 数据库修订注册或浏览器下载。

## 主视图回归发现与修复

`/tmp/advanced-filter-main-cached-visibility.log` 新增真实主视图回归失败：源 D>=10 缓存隐藏行6，改 D<10 后插件缓存正确但原生 `getRowVisible(5)` 仍 false，说明导入把筛选隐藏行同时当成手动隐藏。修复后仅补跑该条：`/tmp/advanced-filter-main-cached-visibility-green.log` 通过，原生行可见性变 true，草稿隐藏行精确为新条件排除的行。主视图十四个向量均已分批通过；未重复全量测试。

## 浏览器验收历史

`frontend/smoke/workbook-advanced-filter-built-smoke.mjs` 与同名 `.md` 已运行。固定构建 `/tmp/four-format-build-20261111.log` 以 exit 0 完成（`built in 42.45s`），浏览器 `140.0.7339.16`，checkpoint `/tmp/xlsx-advanced-filter-built-20261111-final-01`，manifest 固定。三个场景为已有筛选 AND、无筛选确认创建 OR、文本 equal+源人工隐藏。公开 GoTo/Ribbon/dialog/UndoRedo/save/download；保存前和新修订重开时用方向键及复制验证筛选后的可见行。保存调用真实 Python `native_office.patch_office`，实际下载由 ZIP/lxml/openpyxl 回读；逐个 JS response 核对磁盘 SHA256，检查 126 个 JS 资源，无 pageerror。三个产物/receipt SHA256 分别为 `cd5c8179a8165fdbd19125b4eb09d80096423aeed3e67e1d22b47c86e7c0ba1d`、`a704198651cb7c1f366ef599494d44f6480b6b4e9700d1dc111265245ea1921c`、`c9581bdcbd3fc6efd2cbfbd67a593d68731ef6dee0b15782afb4154ed33382ec`；三个文件均独立确认 ZIP CRC、全 XML、筛选条件、隐藏行及单元格数据保全。初次完整轮次三个场景均通过，`summary.json` 是该轮结果。

追加的只读身份/草稿诊断发现 Undo 回归，故 final-01 **不能标记为强化验收通过**。重开修订 2、任何 GoTo/复制前，实际 URL 为 `/reports/v1/native/advanced-filter-built/2`，context revision 为 2、source SHA256 为 `cd5c8179a8165fdbd19125b4eb09d80096423aeed3e67e1d22b47c86e7c0ba1d`，状态“已保存”，`localStorage` 中无 `native-editor-draft` 草稿。之后在新修订上把筛选条件改为 `<10`，状态变为“有未保存修改”；revision 2 同一文件身份的草稿包含 `applySheetOutline`（index 5/7/8 均 `hidden:false`）和 `applySheetFilter`（`<10`、`hiddenRows:[6,7,8]`）。点击 Undo 后页面提示“已撤销上一修改，修改尚未保存”，画布恢复到原筛选可见行，但草稿仍未回到空操作；严格等待 `operations.length===0` 超时。原修订 1 保存 receipt 中同样出现隐藏行 outline 差分。具体值保存在 checkpoint 的 `and-reopened-draft.json`、`and-reopened-criteria-draft.json`、`saved-source-1.json` 和失败截图中；`and-reopened-undo-draft.json` 尚未生成，因为严格断言失败。另有浏览器 clipboard 读回不稳定：活动单元格和截图/公式栏显示值时剪贴板偶发仍是 sentinel；尾行值仍由独立 XLSX 回读验证，筛选可见行的复制检查在初次完整轮次通过。

后续对脚本加入草稿取证和 Undo 空操作严格断言后，续跑复用上述三个成功 receipt（`saveCount:0`，没有重复保存），在 AND 新修订路径因 Undo 草稿不空失败。目录中的旧 `summary.json` 属于前一轮完整运行，**不代表追加的 Undo 诊断通过**。当时要求 outline 差分修复并重新构建后使用新 checkpoint 再跑最终 smoke，且不得复用或覆盖 final-01 的 receipt；后续结果见 final-02/03。


### final-02：outline 修复后确认状态标签问题

固定构建 `/tmp/four-format-build-final2-20261111.log`，checkpoint `/tmp/xlsx-advanced-filter-built-20261111-final-02`。最终续跑 session70769 exit 0，三场景、126 个 JS、`errors:[]`。三来源各保存一次，成功回执被后续续跑复用，无重复保存；最后进程 `saveCount:2` 表示本进程只新保存 OR/文本，不能误读为缺少 AND 保存。三保存操作集均只有 `applySheetFilter`，没有 outline 伪差分；三新修订身份及空草稿通过。AND 改为 `<10` 后精确复制 5，Undo 后操作集为空并恢复精确复制 10，但标签仍为“有未保存修改”。因此 final-02 证明 outline 问题修复，**不能作为 Undo 状态标签已修复的证据**。

之前偶发剪贴板 sentinel 的已确认根因在 smoke 等待：当前 Playwright 的 `frames.js` `waitForFunction` 轮询直接用 `const success = predicate()` 判断，不等待 async predicate；原 `waitForFunction(async () => navigator.clipboard.readText()...)` 返回 Promise 会过早完成。脚本已改为 Node 侧有界轮询，每次 await 实际 `clipboard.readText()`，10 秒内严格匹配预期值；每次仅发送一次公开 Ctrl+C，不重复复制、不放宽结果、不清 localStorage。final-02 和 final-03 均使用该真实读取方式通过。尾行与全部数据仍由独立 XLSX 回读验证。

### final-03：最终强化浏览器验收通过

2026-11-11 root 确认最后构建 session83592 exit 0（`/tmp/four-format-build-final3-20261111.log`，tsc、Vite、预算与构建契约全部通过，Vite 41.68 秒）后冻结生产和 manifest。全新 checkpoint `/tmp/xlsx-advanced-filter-built-20261111-final-03`；浏览器进程 session13810 exit 0。实际读取 `summary.json` 为 `ok:true`、三场景、`saveCount:3`、`resourceCount:126`、`errors:[]`，浏览器 `140.0.7339.16`。清单 SHA256 `184c94a96f863198c30ffcfaae1ec2169a8e6b6df2eaca50415bbd62538eada5`，与冻结磁盘一致；所有实际 JS response 也逐个匹配磁盘 SHA256。

三个来源各保存一次、真实下载一次；保存操作集都只有一个 `applySheetFilter`。回执、修订文件与实际下载 SHA256 一致：

| 场景 | 新修订 | SHA256 | 实际隐藏行（1 基） |
| --- | --- | --- | --- |
| 已有筛选 AND | 2 | `8d5acc140b60d9e25313298982dd7d83e4cdda846ef86357b54802613efbd00e` | 6、8、9 |
| 无筛选创建 OR | 11 | `b761f791b3bf215b4c7884af6c1787487a734005c58b6348fcd31d1c57500385` | 7、8 |
| 文本 equal + 人工隐藏 | 21 | `ab6a7bf49dc0761486bdd9017839f3c779ee4e3da7068d815a8ef41fbe912151` | 7、8 |

三文件均通过 ZIP CRC、lxml 全 XML、openpyxl 筛选条件与隐藏行核对，`C5:E9` 偏移范围、其它列条件、人工隐藏、表头和范围外尾行均保留，全部单元格值与源文件一致。三个新修订均明确打开，context revision/source SHA256 对应，初始标签“已保存”，该修订草稿为空；公开方向键与精确复制确认画布可见行。

AND 加强链路也全部通过：新修订将条件改为 `<10`，精确复制 5；Undo 后草稿操作集严格为空、标签“已保存”、精确复制 10；Redo 后草稿与修改条件时完全一致、标签“有未保存修改”、精确复制 5；再次 Undo 后草稿与第一次 Undo 完全一致、标签“已保存”、精确复制 10。证据为 `and-reopened-{draft,criteria-draft,undo-draft,redo-draft,final-undo-draft}.json`、`and-result.json` 和最终 summary。三张 `{and,or-create,text-equal-manual}-reopened.png` 均已实际查看，显示正确新修订、已保存和预期筛选行。

本结果只覆盖冻结构建与本地模拟 HTTP 的原生 context/file/save/download 边界，保存 patch 使用真实 Python，下载使用真实浏览器；**不代表真实数据库修订注册或完整服务器部署验收**。未运行全套测试、未重建、未提交。
