# Word 行跨页 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-row-breaks-built-smoke.mjs
```

默认4242，可设 `DOCX_ROW_BREAKS_SMOKE_PORT`；故障定位后 `DOCX_ROW_BREAKS_START_REVISION` 可窄续跑，避免重复已通过来源。只启动preview，不build；必须等待root统一dist与最终doc_engine bridge。

普通/纵合并hidden continuation/RTL/合法成对cantSplit四源。真实Word页高10000twip、上下边距1000，正文12段引言后接3×2长表；首行header+exact且cantSplit显式val0，中间目标atLeast行18段各20px、cantSplit=true，末行无cantSplit。merged仅左侧跨中间/末行，目标文字位于未合并右格，保隐藏continue正文；paired目标原始为空成对cantSplit。保奇数网格3001/4001、row属性、原段落rsid、中英文emoji、mixed runs、底纹、height/header等。

从现有table-properties的“行跨页”独立导航进入；caret及真实鼠标混合矩形无操作不dirty、混合checkbox indeterminate/aria-checked=mixed。允许→禁止→允许三条严格步骤（均top1/bottom2），UndoRedo、草稿刷新、真实Python patch/HTTP下载SHA/ZIP、明确修订重开。仅mask cantSplit后整个document.xml全文逐字、所有physical cell/隐藏正文/非目标行全文及其他ZIP parts身份保持。

关键验收是公开“分页预览”的真实页面几何：逐页对TARGET-LINE-00..17的文字Range与所有祖先clip/page相交，排除重复但不可见的clone；18条均实际可见。初始禁止状态目标第00行须整体推至第二页，允许后须从第一页起排并横跨至少两页；再禁止立即恢复初始分页，草稿恢复及server保存重开必须与live允许分页完全一致。尤其普通与paired必须同时核验live/重开，不能只检查data-cant-split或绕过raw XML旧标记。每状态输出PNG/HTML与visible-lines/pages/window证据。所有JS要求HTTP200+本地SHA、console/pageerror空。

授权/修订使用本地夹具，实际DOCX inspect/patch为项目Python接口，下载走临时真实HTTP服务；不宣称生产授权HTTP、桌面Word或PDF完全等价。最终统一构建 `/tmp/office-row-breaks-trace-pane-build.log` 后四来源实测完成。最后paired窄续跑session7578终态exit0，`/tmp/word-row-breaks-built-smoke.log` 为 `ok=true/errors=[]`、121个JS HTTP200/SHA。普通与merged首轮完整通过，产物 `/tmp/docx-row-breaks-built-bVv3NZ/`；RTL窄续跑完整通过，产物 `/tmp/docx-row-breaks-built-6AwFKZ/`；paired最终通过，产物 `/tmp/docx-row-breaks-built-7A7E0F/`。分别保存/下载修订2/11/21/31，各有初始禁止、允许、再次禁止、草稿允许及新修订重开预览PNG/HTML。

四源均实际观察：禁止时TARGET-LINE-00在第二页；允许后第一页可见00–11，第二页12–17，18行无丢失。两态页数都是2，但页面切点从280.7px变为533.3px，实际整行推移与跨页拆分不同；再次禁止精确恢复初态，草稿恢复/live与真实保存重开页面和可见行完全一致，paired没有raw XML旧标记导致live/保存偏差。每源保存严格包含allow true→false→true三步。UndoRedo、mixed无操作、Python/HTTP下载、仅mask cantSplit全文及其他parts/physical cells/hidden/非目标行保真均通过。root已目视merged两态，UI agent已目视普通允许态。

首失败仅RTL异步autospace的class token顺序/捕获时机，保留 `/tmp/word-row-breaks-built-first.log`；probe改为保留所有class token但排序，并紧邻set捕获undo基线，没有丢弃attrs/style/text。第二次paired失败是probe mask贪婪跨匹配（前行自闭合与后行成对元素），`/tmp/word-row-breaks-paired-exact.diff` 明确实际XML唯一变化是正确删除目标成对cantSplit；分支修正后保持严格全文断言通过。失败日志 `/tmp/word-row-breaks-built-paired-mask-failure.log` 保留。两次均只窄续跑剩余来源，未修改产品、重建或重复已通过来源。

四源每份 `revision-{source}-result.json`、四个下载SHA、最终121资源SHA及结果路径汇总 `/tmp/word-row-breaks-built-evidence.json`。前两source结果由现有HTML/ZIP恢复，明确记录原运行完整断言通过但原脚本未逐源保存visible-line数组，不伪造数组；后两source保留真实运行完整数组。
