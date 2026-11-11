# Word AutoFit 三入口 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-autofit-built-smoke.mjs
```

默认4242（可用 `DOCX_AUTOFIT_SMOKE_PORT` 覆盖）；只使用root已统一构建的assets/bridge，不build。真实fixed/contents/100%window/70%pct来源（70%pct有效mode为contents，保留70%首选宽度），奇数不等grid1801/2401/3001；含缺tcW与复杂横纵合并/隐藏continue、多段混合runs、rsid、主题tcPr/pretty空白。

每来源公开入口直接fixed保留奇数grid，真实save/Python patch/HTTP下载/ZIP回读/新修订重开；再contents→window→undo/redo→fixed，完整有序steps保存且节宽回退[3000,3000,3000]，草稿刷新精确DOM还原。额外逐修订保存contents→window→fixed，使三种最终mode均有真实下载和回读。核对mode、layout、每个物理tcW按grid span求和、非几何XML逐字与其他parts SHA不变、物理来源格身份不变；JS200且SHA匹配本地，console/pageerror为空。

准备状态：Node语法与嵌入Python compile通过；尚未执行built。UI/API已冻结，不在本脚本里构建。

最终 built 实测（2026-11-10）：首轮session19652 exit0，`/tmp/word-autofit-built-smoke.log` 为 `ok:true/errors:[]`；Chromium140.0.7339.16；产物 `/tmp/docx-autofit-built-Mw4BvQ/`。全部13次真实保存/HTTP下载通过，没有放宽断言或重建生产。

五原始来源：fixed、contents、70%pct（effective contents）缺tcW、复杂横纵merge及隐藏continue、100%window。直接fixed下载保奇数grid `[1801,2401,3001]`；每源再次执行完整contents→window→fixed，undo/redo与draft精确恢复，实际patch后 `[3000,3000,3000]`。额外逐修订三种最终模式都保存并下载回读（51=contents、52=window、53=fixed），网格 `[3120,3120,3120]`。每个实际物理tcW为对应span网格和，mode/layout正确；只删除四类几何tag后document.xml逐字相同，其他parts SHA与逻辑/物理cell身份均保持。

截图/HTML：`revision-2/3/11/12/21/22/31/32/41/42/51/52/53-autofit-reopened.png/.html`（展开为对应单个修订文件名）。已目视rev32与51：复杂合并的MERGED、C1/C2、外部前后、中文emoji/混合格式完整；contents最终模式及普通各格多段保持。所有实际JS200，SHA与最终构建assets匹配；完整loadedChunks见日志。

UI定向证据：`/tmp/word-autofit-ui-red.log`首次缺module RED；`/tmp/word-autofit-ui-green.log`首4项GREEN；`/tmp/word-autofit-ui-replay-green.log`真实collector/replay与奇数精度2项GREEN；`/tmp/word-autofit-ui-active-green.log`选中态1项GREEN；`/tmp/word-autofit-ui-guards-green.log`新增无表/nested/新表/mixed守卫1项GREEN；最终`/tmp/word-autofit-ui-types.log` exit0。总7项分别验证，未重复完整测试。
