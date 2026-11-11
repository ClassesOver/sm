# Word 整表对齐 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-alignment-built-smoke.mjs
```

默认4242，支持 `DOCX_TABLE_ALIGNMENT_SMOKE_PORT`；故障定位后以 `DOCX_TABLE_ALIGNMENT_START_REVISION` 窄续跑，或用 `DOCX_TABLE_ALIGNMENT_RESUME_DIRECTORY` 指向上一产物目录。续跑校验已通过保存的DOCX SHA并复制文件，完整来源与已通过对齐直接复用，失败对齐继续验证。只启动vite preview，不build，等root最终统一frontend与doc_engine bridge。每来源、每次保存立即持久化独立结果，避免后续失败丢失已通过证据。

八来源组合：LTR legacy15正indent333、LTR legacy14负indent-109、RTL raw start+正缩进、RTL raw end成对jc+legacy14负缩进、50%宽度、2×2合并hidden continuation、真实浮动tblpPr X777/Y111、同定位但行高总和14000twip触发真实suppressed。全部保存原整数网格1801/2401/3001、原tblInd/width/legacy settings、物理tc属性及隐藏正文、中英文/emoji/rsid/混合runs、所有非目标parts。

公开table-properties保留原边距dialog，独立“整表对齐”导航；起始侧沿source删除jc（PM重开null），RTL为右起始侧，right不擅自交换。原start/end alias无操作不变DOM与几何，不规范化raw；真实/抑制浮动显示定位优先提示并检查真实CSS float分支。每源保存三种对齐（共24次），caret、真实table handle NodeSelection、鼠标CellSelection分别只定位同一整表；每次改值往返后最终协议仅一个setTableAlignment最后值。每次UndoRedo/草稿/真实Python patch/HTTP下载SHA/ZIP/新修订重开均核验。

实际几何读取table box相对PM内容左右边距和width/height：LTR起始<居中<右严格递增；RTL居中在两种右侧语义左方，right与起始的偏移差等于显示indent/15（容差2px）。legacy14显示indent按既有导入规则从signed原indent扣物理首格左边距（由XML读取），不按RTL镜像为右边距。真实/抑制浮动保存jc但当前位置及宽度保持不变。每个明确保存修订的实际位置/宽高/margins/float与live精确相同。所有物理cell全文、仅mask直属tblPr/jc后完整document.xml与其他ZIP parts身份保持，不mask段落jc、不改缩进/宽度/浮动。所有加载JS要求HTTP200+本地SHA且console/pageerror空。

产物每个case有 `revision-N-{alignment}-reopened.png/.html` 与真实下载DOCX，每source有 `{source-name}-result.json`（每次保存更新，完成后complete=true）。最终JSON记录全部operations、实际box和JS SHA。授权/修订路由为本地夹具，实际inspect/patch用项目Python、下载临时真实HTTP；不宣称生产授权HTTP或桌面Word/PDF等价。

Node语法、嵌入Python compile通过。当前built尚未全部通过：`/tmp/docx-table-alignment-built-bOU9kG` 中LTR legacy15三次保存、LTR legacy14 right保存通过。legacy14 left的XML/下载身份已通过，但明确修订重开左偏移为-9.5px，live为-7.3px；首格33twip左边距导致legacy导入缩进差异。失败日志 `/tmp/word-table-alignment-built-legacy14-indent-failure.log`，待修复后以该目录续跑剩余20次保存，禁止重复上述四次通过保存。


最终专项通过：session43704 exit0，`/tmp/word-table-alignment-built-smoke.log` ok=true/errors=[]，累计8来源24保存。首4来自bOU9kG旧dist；最终统一dist新增18次到uzsklO；从uzsklO复用22份已验SHA文件，仅执行最后2次到rdefw0。高表NodeSelection探针改为首段真实居中滚动再hover/click手柄，未force或改生产。最终121实际JS HTTP200+SHA通过；完整manifest `/tmp/word-table-alignment-built-evidence.json`，24份下载DOCX及source结果 `/tmp/docx-table-alignment-built-rdefw0`。分dist、截图分布、资源SHA与失败保留详见 `../../NATIVE_WORD_TABLE_ALIGNMENT_ACCEPTANCE.md` 最终段落；旧失败记录作为过程证据保留。
