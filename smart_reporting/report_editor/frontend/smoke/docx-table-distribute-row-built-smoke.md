# Word 均分行高 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-distribute-row-built-smoke.mjs
```

仅使用root最终构建，不build；preview默认4242（`DOCX_DISTRIBUTE_ROW_SMOKE_PORT`）。同一真实DOCX3×3表，三行不同多段内容、首行exact，混合runs/中文emoji/主题底纹/cantSplit/原XML空白。

公开缩放入口设100/150/75%，相同caret均分整表，真实TR内容测量后输出twip须完全相同；核对root zoom原值恢复，精确DOM undo/redo、草稿刷新、明确修订重开；实际保存/项目Python patch/真实HTTP下载/SHA/ZIP回读。每个步骤必须新distributeTableRows意图、三行同目标、无条件atLeast。额外真实鼠标CellSelection前两行局部均分，第三行不动。脱敏trHeight后整个document.xml逐字相同，其他parts SHA及cell来源身份不变；所有JS200且SHA匹配本地，console/pageerror为空。

准备：Node语法及嵌入Python compile通过，尚待最终统一build后真实执行。

最终真实 built（2026-11-10）首轮session39092 exit0，`/tmp/word-row-distribute-built-smoke.log` 为 `ok:true/errors:[]`；Chromium140.0.7339.16，产物 `/tmp/docx-distribute-row-built-n70w1P/`。

公开缩放入口100/150/75%相同caret输出严格 `[1312,1312,1312]` twip，三次均覆盖逻辑行[0,3)，实际下载回读三行均1312/atLeast。局部真实鼠标CellSelection为[0,2)，实测927twip、第三行原500保持。每档DOM undo/redo、临时zoom恢复、草稿刷新、新修订重开全部精确匹配；真实patch/下载SHA、仅trHeight变化的整XML逐字、非目标parts/cells来源身份通过。

目视产物 `zoom-100-reopened.png`、`zoom-150-reopened.png`、`zoom-75-reopened.png`，局部 `local-rows-reopened.png/.html`；首张为修订2、局部为修订41。已目视首张与局部：外前后段、三行三列不同段落数、中文emoji与混合runs均保留。atLeast目标高度一致不保证内容更高行的最终视觉高度一致，符合固定源码。

定向测试证据：`/tmp/word-distribute-row-ui-red.log` 初始均分入口RED；`/tmp/word-distribute-row-ui-green.log` 11UI+4测量15GREEN；`/tmp/word-distribute-row-cancel-red.log` 取消挂起RED，`/tmp/word-distribute-row-cancel-green.log` 新取消/deadline/listener向量1GREEN；最终types `/tmp/word-distribute-row-ui-final-types.log` exit0。真实host测量13向量 `/tmp/word-distribute-row-host/run.log`：root/wrapper100/150/75%均705twip，缺失行拒绝并恢复zoom。字体ready仅等待布局稳定，浏览器fallback正常参与实际测量；15s deadline、100ms失效检查和finally资源释放，未宣称字体下载必成功。
