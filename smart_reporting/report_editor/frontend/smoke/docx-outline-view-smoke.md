# Word 大纲视图专项

固定源：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。

接线：createDocxOutlineView 接收真实 Editor 与 .docx-native 下的嵌套 wrapper；root class 为 view-outline，沿用源 scoped.css。docx-outline-view.css 在 docx.css 之后加载，覆盖宿主均匀分栏显示，并在大纲内取消混排 decoration 的视觉位移、列宽和分栏浮动占位；保留全部页面/分栏参数及 inline --col-*，退出自动恢复。

专项单测：npm test -- src/docx-outline-view.test.ts。覆盖真实 editorExtensions、真实折叠句柄、plugin state/decorations、退出/销毁清理、原 class 恢复、JSON/update/undoDepth 不变、只读/保存 Guard。

冻结并统一构建后执行：DOCX_EXPECTED_MANIFEST_SHA256=<冻结hash> node smoke/docx-outline-view-smoke.mjs。缺少或不匹配 expected hash 时立即失败。DOCX_TEST_DIST 指定冻结前端目录，DOCX_TEST_ENGINE 指定冻结 doc_engine 根目录，DOCX_TEST_OUTPUT 指定截图与 result.json 输出目录，DOCX_TEST_PORT 可指定端口。探针只启动 preview，不构建；fixture inspect 使用指定 engine，并记录 dist/edit-docx.mjs 执行前后 SHA-256。

真实 DOCX 包含 h1/h2、正文、表格、均匀双栏和两节混排。可编辑与只读 context 均通过真实 View 标签和页面视图/大纲按钮切换，点击源大纲句柄折叠/展开，退出恢复全部内容。核对 localStorage 原生草稿、保存状态、正文文本、页面 style、分栏恢复一致，保存请求为零。所有实际加载 JS 逐个与冻结目录磁盘 SHA-256 对照，manifest 前后身份不变。

源边界：源 outline-view 使用 collectHeadings(doc, undefined, true)，因此仅 docHeading 产生折叠句柄；虽然 collectHeadings 的其他消费者可传 styles 识别样式标题/编号列表标题，此源插件并未传入。源 CSS 也仅保留 h1–h6。当前忠实保留该边界，不扩大为 Web/阅读视图，不更改正文 attrs，不把隐藏状态写入导出。

大纲仍可编辑正文标题；实际正文编辑继续经过现有 Guard，视图与折叠仅 dispatch plugin metadata。切回页面清除 collapsed 集合；dispose 清除 plugin 状态并恢复原 view-outline class。

## 2026-11-11 实测记录

冻结 final2 manifest：d16219950a133f029b252e955593dc52b6693013f0e146bbce73fcddf6e2c3e2；engine bridge：ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。目录：/tmp/sr-word-navigation-20261111/final2-static、final-engine。

均匀双栏 editable 和 readonly 隔离专项均通过，每路实际加载 125 个 JS，逐个磁盘 SHA-256 一致，errors=[]，savePayloads=[]，engine 前后身份一致。可编辑路线含真实叶标题输入 EDIT、NativeDraft 增加和 Ctrl+z 恢复。证据分别位于 /tmp/sr-word-navigation-20261111/outline-browser/editable-final2/result.json、readonly-final2/result.json，并有对应 outline.png、expanded/folded-geometry.json。

混排回归 RED：原冻结 mixed 大纲残留列位移，OUTLINE-B translate(312,-167.34)、OUTLINE-C translate(0,-124.37)，导致 C 的句柄截获 A 点击。初始 failure.html/png 和定向几何 RED 保留于 /tmp/sr-word-navigation-20261111/outline-browser/ 与其 mixed-geometry-red/ 子目录。新增 expanded/folded 几何断言，禁止可见标题行重叠，不使用 force click。DOCX_OUTLINE_CASE=mixed 可定向复跑。

最终 final3 三场景 GREEN：均匀双栏 editable、readonly、两节 2 栏→1 栏 mixed 一次完整专项通过。冻结目录 /tmp/sr-word-navigation-20261111/final3-static，manifest 6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8。125 个实际加载 JS（含解析 worker）逐个与冻结磁盘 SHA-256 一致，engine 前后均 ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6，errors=[]，savePayloads=[]。未构建、未注入临时 CSS、未使用 force click。

最终证据：/tmp/sr-word-navigation-20261111/outline-final3/result.json；截图 editable-outline.png、readonly-outline.png、mixed-outline.png；每个场景各有 expanded-geometry.json 和 folded-geometry.json。已目视 mixed 截图，A/B/C 无重叠。mixed 展开时四个标题行 top 分别 400.34、439.83、496.16、554.34px，全部 transform:none；折叠后 A/B/C top 为 400.34、458.53、516.72px，真实点击展开/再次折叠均成功。

三场景均通过退出后正文、表格、原 page inline style、分栏 column-count、原生草稿、保存状态精确恢复检查；纯视图没有保存请求。可编辑场景实际普通叶标题输入可创建正文草稿并由 Ctrl+z 恢复。JSON/update/undoDepth 不变与只读/保存 Guard 由真实 editorExtensions 专项 3/3 单测证明；浏览器未直接读取内部 undoDepth，不将其表述为浏览器观察值。以上为本地 fixture 及冻结构建验收，不代表生产鉴权或真实线上发布验收。
