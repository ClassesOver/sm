# PDF 文字快捷提交、表单画布微调与 DOCX 精确底色（2026-11-11）

固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批完成三项限定技术增量，排除 OCR。整体 PDF 对齐、完整内容/版式保真与生产上线验收仍未完成；未提交、部署或启用生产开关。

## 实现范围

文字：固定 App.tsx 原有 Ctrl/Cmd+Enter 调用 commitTextDraft，本地原位改字 textarea 漏接。本批新增独立快捷键 helper，调用现有带身份、锁定、预览、保存及草稿排他检查的提交按钮。普通 Enter 继续换行；IME/composing/229、长按、Alt、已处理事件、禁用、只读和隐藏控件不提交。原选区样式和唯一对象操作保持，AbortSignal 清理监听。没有接页面内完整游标或跨对象 reflow。详见 NATIVE_PDF_TEXT_EDIT_SHORTCUT_ACCEPTANCE.md。

表单：按固定 FormDesignLayer/App 的选中和 nudge 行为，新增安全独立单 Widget 的画布选中与方向键 1pt、Shift 10pt 微调。复用现有完整来源/字段/Widget 身份和 editFormWidget.rect；连续按键累计成一项操作，可 Undo/Redo，回到原矩形则清除该项。按各页旋转映射显示方向并限制在 CropBox 内，不改变控件大小。仅默认 UserUnit、select 模式及 formDesign tab；输入框、编辑面板、Ribbon、弹窗、外部活动、预览和保存期间不截键。字段本身多 Widget、拖动/resize、字段迁移和任意混合草稿未开放。详见 NATIVE_PDF_FORM_CANVAS_NUDGE_ACCEPTANCE.md。

转换：PDF IR 已保留 RGB 底色，但固定 DOCX 映射只近似命名高亮色，会丢失浅色。本地仅修改 converter rebuild/index.ts，复用共享 Run.shading 写精确非命名 RGB，并把 shading 纳入 run 合并判定。15 种非白命名色仍使用原 highlight，白色保留无底色规则，非法值不写。正文、表格和 frame 复用原路径，不修改共享 writer、字体、布局或依赖。属于固定源上的本地保真适配；脚注 NoteRun 没有底色载体，本批不支持。详见 NATIVE_PDF_DOCX_EXACT_SHADING_ACCEPTANCE.md。

## 专项与真实失败

- 文字 helper：先空实现行为 RED（2 failed / 12 passed），实现后 14 项通过；窄 strict tsc 通过。
- 表单：原 10 项真实行为 RED→GREEN，inactive 生命周期、Ribbon/modal 隔离各新增 1 项独立 RED→GREEN，共 12 项分批通过；窄 strict tsc 通过。另有四旋转 native→pypdf 产物，各复读 37 个原对象/流，仅目标 Rect/AP 例外，不宣称对象零增长。
- DOCX：真实 PDF→PDFium IR→DOCX 等 5 项中 4 项真实 RED、原命名色边界原已通过，实现后 5 项通过；生产文件窄 strict tsc 通过。测试入口保留原有 wasm-path/resourcesPath 两条诊断，不冒称全项目类型检查通过。独立 verifier 拒绝 10 种变异。
- HTTP review-docx 强化为真实浅黄色来源和实际 DOCX 精确 shd 断言，旧运行包真实失败，新包通过。受影响 editFormWidget 后置审核故障和签发静态守卫一起共 3 项通过，日志 `/tmp/pdf-shortcuts-nudge-shading-http-green.log`。

真实表单浏览器先捕获同页两个命中框：同 generation 的并发 renderPage 在 await TextLayer 后，过期任务也追加 overlays。root 加入当前 holder 仍持有该 canvas 且页面仍可见的检查；sync=false 的脱离 DOM 控制器同时 dispose 清监听。第一次失败日志保留，最终实际每页唯一命中框通过；没有用 selector 过滤重复项冒充修复。

后续 90° 位移检查失败来自 QA 比例计算：SVG 几何和 DOM client 为 20×20，但 Playwright boundingBox 把 2px 选中描边计入，返回 22×22，旧脚本误算 scale=1.1。只读真实探针 `/tmp/pdf-form-canvas-bbox-probe.json` 确认 screenCTM 为 1，实际 SVG x180/y60→x181/y50 正确。只修 smoke：用无描边 SVG 几何定比例，记录 DOM/page-relative 与 Playwright 坐标后再断言，容差不放宽。历史 nudge0 的旧 scale=1.025 作废而不改写历史检查点；其已记录 client delta=[1,-10]、实际 PDF delta=[1,10]，没有用新测量重跑该保存。最终 nudge90 的新测量 scale=1，page-relative=[180,60]→[181,50]。

## 冻结构建与恢复边界

三次成功 Vite：r1 用于文字/DOCX 浏览器和表单前两次字段创建；发现渲染竞争后第二次构建未作浏览器验收，又被包含 detach-dispose 清理的最终第三次构建替代。不是三次重复完整测试。bridge bundle 和 runtime package 各一次；中途一次清单脚本工作目录错误在写入前失败，纠正后核对成功，未重复 bundle。一次预算汇总脚本语法错误也已纠正，未作为预算通过证据。

- r1 static：`/tmp/pdf-shortcuts-nudge-shading-static-r1`，manifest `c22dc903c579bb21472d9d8eab2ad7c16f0af1cce99537ed4cdb2a591f74a370`。
- final static：`/tmp/pdf-shortcuts-nudge-shading-static-final`，manifest `6c4e0445b2d9e0038a8b1a84eec85fcb5d22a16d6cf0a4555e5c46ea572bb0cc`。
- runtime：`/tmp/pdf-shortcuts-nudge-shading-runtime`，CLI `1b1cec12eb0d22057fe713fa415bc858055ca317a4c5cd0fdd221539960fb667`。
- final 376 个 JS 分块预算零超限，PDF main 251288 bytes、form controls 40359 bytes，未放宽预算。
- 49 个前端文件、192 个引擎/清单文件、955 个 bundle inputs 最终核对匹配；LOCAL 187 项、converter local 48 项、固定 Git blob 69 项匹配。来源 hash 与 local hash 分列不混用；运行包来源、许可、三转换引擎通告和两个 WASM 核验。
- 打包后发现共享 workbook SOURCE.md 被并行文档编辑更新，只补复制当前通告并逐字节重核；实际 955 个 bundle inputs 对上一批仅 converter rebuild/index.ts 改变，没有因此重打运行包。

表单保留原 server 和已保存修订：r1 完成 text/check 两次创建后，在 checkpoint-r1.json 原样归档并核验 37 个旧资产及实际 PDF；checkpoint.buildTransitions 显式记录 r1→final，静态 alias 切到 final。随后只续跑 nudge0、rotation、nudge90，90° QA 失败时已完成四次保存，再仅重试尚未保存的 nudge90。最终五次保存 revision 4→9，没有重做已通过保存。

## 实际浏览器、下载与宿主

三域均使用真实 grant、cookie、CSRF、生产静态资源、打包引擎、签发下载；文字和表单还覆盖实际预览确认与保存后重开。仓储为内存 fixture，不等于生产持久化、权限或网络验收。文字和 DOCX 各核对 r1 的 37 个实际 JS；表单 final 核对 37 个实际 JS，旧 37 项另存 transition。两版资产分别核验，不宣称所有浏览器在 final 重新运行。各成功链路的 asset/page/console/HTTP errors 均为空，来源不变。

文字目录 `/tmp/pdf-shortcuts-nudge-shading-text-browser`：普通 Enter 实际换行而无操作；Ctrl 提交 AABBCD，Meta 确实改为 AABBCC，仍为同对象唯一操作并保留选区样式。一次保存 revision 4→5，实际 PDF 12030 bytes，SHA `64fd35c8bf2d3d3ca81e0daa891bb1e17775c63d77537bfb8ae091e518992334`。独立 pypdf 字体、基线、红色和其他页检查通过，root 已目视实际 PDF。未在后续 final 构建重复该链。

表单目录 `/tmp/pdf-shortcuts-nudge-shading-form-browser`：五次保存、下载和重开完成；nudge0 实际 6164 bytes、SHA `5c7959bd375b3096569103dd75aebb9bf5bed934401c47bb81bb377c98fe50dc`，nudge90 实际 6403 bytes、SHA `967ba91de40e1c5ec92735720f577c307525e9b7a2b8c987548b6a94085fedda`。独立 pypdf 分别复读 28/31 个原对象，只有目标 Rect/AP 可变；正文、原流、字段树、值、未选 AP 和页归属保持。root 已目视最终三页。真实浏览器覆盖 0°/90°，180°/270° 与两档缩放来自专项测试，不冒称浏览器穷尽。

DOCX 目录 `/tmp/pdf-shortcuts-nudge-shading-docx-browser`：实际 4601 bytes、SHA `c5db2b6712885cb0368f460028ee15957abbe80bf3dfb58c2f7ac954a3fd57f3`。独立 ZIP 确认浅黄色 FFF2CC、浅绿色 E2F0D9 为精确 shd，黄色 FFFF00 仍为命名 highlight，Plain/White 不误着色。对该实际下载仅运行一次 LibreOffice Writer 打开并转 PDF，profile/output 放在 `/dev/shm/pdf-shortcuts-nudge-shading-writer-{profile,output}`；exit0，保留非 fatal javaldx 警告。实际 rendered.pdf 一页、SHA `4668c89a6b45ab935c0a9e3f71ccc69fe41cf95a09c9feb74e6350f08c5b83c8`。独立读取宿主实际绘制底色均与来源精确一致，root 已目视，hostExactShadingVerified=true，overallFidelityPassed=false。没有重跑旧 Impress/Calc。

## 非阻断与仍开放范围

所有实际保存/转换继续保留 validation.ok=false 与具体待核原因，不将技术专项冒充业务验收通过。实际身份可读的文件与下载照常保留。没有新增 Python 签发函数或后置失败步骤，强化已有故障注入而不改签发链；未重复完整项目测试。

仍开放页面完整游标、任意混合/跨对象 reflow，表单拖动/resize/多选复杂字段、CJK/日期属性、XFA/签名，DOCX 脚注底色与完整 Office/MD/HTML 内容版式保真、PPTX 首基线/宿主表格链接色、XLSX 二维图文与分页，以及生产镜像、真实权限/网络/部署验收。OCR 排除。总证据为 `/tmp/pdf-shortcuts-nudge-shading-final-evidence-20261111.json`。
