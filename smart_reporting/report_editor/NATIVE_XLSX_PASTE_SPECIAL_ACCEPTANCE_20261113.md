# XLSX 完整选择性粘贴验收（2026-11-13）

当前状态：源码、定向测试、真实源码浏览器与immutable生产资源验收均已通过。

## 来源与实现

固定GenOffice源commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。完整移植 `paste-special.ts` 和 `shared-formula-journal.ts`，以现有DOM modal适配 `PasteSpecialDialog.tsx` 的完整结构及源可用性规则。保留原5快捷粘贴，新增完整对话框、Ctrl+Alt+V、原生cell context menu。保存沿用既有网格编辑日志、NativeDraft和native修订签发，无新后端writer。

对话框展示12类型、5运算、跳过空单元、转置与粘贴链接。源引擎不支持的批注/验证展示但禁用；内部剪切仅整体，外部文本仅全部/数值及转置。运算和转置公式沿用源缓存值语义。自动扩容走官方插行/列命令，各自有原生历史；不宣称跨扩容单事务Undo。

captured workbook/sheet/range在来源读取、应用及扩容异步前置阶段核验；迟到来源、取消、readonly、protected、命令false不标记成功。扩容内部选区变化通过官方子命令完成回调恢复captured FRange，用户在异步前置期间移动目标会被拒绝且不扩容。

## 已有证据

证据根：`/home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113/xlsx`。

- 算法7与实际Univer2：`real-writer.log`；完整DOM对话框5：`dialog-green.log`；原剪贴板入口：`ribbon-clipboard.log`。
- 真实宿主草稿/UndoRedo/取消/保存独立readWorkbook：`host-save.log`；readonly/protection不写入：`host-protection.log`。测试宿主fixture缺官方clipboard插件，只替身来源读取，不替换writer，实际clipboard证明见浏览器。
- 真实跨行列边界扩容：`real-bounds.log`原始RED、`real-bounds-green.log`GREEN；异步期间用户改目标无扩容/无写入：`real-bounds-stale.log`。
- `browser-source-v4/evidence.json`：实际UI Copy→加法/转置/值与数字格式/粘贴链接→UndoRedo→草稿reload→真实save→下载→openpyxl独立核对→明确saved.editor.openUrl复开，复开api/file SHA与下载相同；source原件SHA不变，plannerCalls0。1440×900、1024×480、390×844动作命中且截图可回读。
- `browser-controls-v2/controls-evidence.json`：实际CtrlAltV及原生右键入口、取消无保存无草稿。
- `source-provenance.md`、`source-ready-sha256.txt`：来源、本地适配与源码身份。engine的254输入SHA与既有构建逐项相同，未重复构建。

## 正式冻结验收

必须以root统一构建static运行 `frontend/smoke/workbook-paste-special-smoke.mjs`（不设置DEV），同一次完成真实复制、完整入口、委托普通values、own-layer运算、原生历史、草稿恢复、save/download/openpyxl及新修订复开，逐个HTTP资源SHA与磁盘比对且manifest前后相同。此段在执行前不宣称通过。


## 冻结正式结果

`browser-frozen-v1.log` exit 0，`browser-frozen-v1/evidence.json` 为完整结果。root统一tsc、Vite与原build budget通过；source-v2的manifest SHA `7949df1457ac33345c20d4ba447bc26d0a922881f8812040838bf82d6f00e0a8` 在运行前后相同，实际283个HTTP静态资源逐个与该冻结磁盘内容SHA匹配。browserErrors与consoleErrors均为空。运行脚本身份在 `frozen-runner-sha256.txt`，产品最终身份在 `source-ready-sha256.txt`。

此单次正式运行包括完整12/5对话框、CtrlAltV、原生右键、真实UI Copy、官方无flags数值粘贴与own-layer加法/转置/值和数字格式/粘贴链接、UndoRedo、草稿reload、真实保存r4→r5、实际下载、独立openpyxl/ZIP与明确新修订复开。下载SHA `51d3b926650e5aef27f7f5a72eb9aafd32b8e602d6952a5c8ad95557b739f480` 与签发、独立读回和新修订api/file一致。原件SHA `9001d625e357c1df4cc04b061fc4235815939d5ff389a8c7c4b6c5ab70ac2f84` 未变，plannerCalls=0；仅sheet1.xml与styles.xml变化，邻接文字、原公式和另一工作表保留。1440×900、1024×480、390×844动作均实际命中，1024×480 body真实wheel滚动通过。

发布验收结果保持 `validation.ok=false`，原因 `native_source_review_pending`：文件已保存，业务事实与完整版式尚未重新核验。该告警未被伪标通过，且不阻止已核验实际XLSX的下载签发。
