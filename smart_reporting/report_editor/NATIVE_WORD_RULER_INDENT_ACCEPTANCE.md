# Word 标尺左／首行／悬挂缩进增量验收

日期：2026-11-11。固定源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。承接 [标尺与页面验收](NATIVE_WORD_RULER_PAGES_ACCEPTANCE.md) 及 [字符首行验收](NATIVE_WORD_CHARACTER_INDENT_ACCEPTANCE.md)。

后续：[制表位增量验收](NATIVE_WORD_TAB_STOPS_ACCEPTANCE.md) 已在100%缩放、可信单段范围开放制表位编辑。下文保留本批当时的范围及构建证据。

## 范围及来源语义

原有可信顶层普通正文／标题的单段、单栏、非镜像、无非零字符缩进、LTR 来源，标尺现可编辑左缩进、首行及悬挂缩进。复用已经迁入的固定源 `Ruler.tsx`，沿用源 90 twips 吸附、键盘、鼠标、单位和缩放坐标计算：

- 左方块移动所有行，保留首行相对偏移。
- 首行三角仅改变首行偏移。
- 悬挂三角同时改变左缩进和有符号首行偏移，保持首行绝对位置。

新增原子 `setParagraphRulerIndent`，只接受非空的 `leftTwips`／`firstLineTwips` 整数字段，范围各为 −14400..14400。它与旧工具栏的非负 720 twips 步进操作分开；共享 normalizer 用于前端意图及 Node 校验。每次手势形成独立 UndoRedo 步骤，连续手势合并为同段一条保存操作；草稿保留显式意图并严格回放。同段已有正文或其它格式改变时要求先保存，前端 Guard、collector、回放和后端整批校验共同拒绝混改及重复操作。

后端 inspect 提供来源能力及只读原因，patch 再次校验来源身份和能力。写回复用既有 `mergeCellParaFormat`，只改请求的缩进字段；显式零值和继承缩进均可覆盖。未另造 OOXML 写入器，未改变产物签发链路。

制表位仍只读；列表、表格、跨段、新增未保存段落、页眉页脚、文本框、多栏和镜像目标未开放。本批不把字符单位转换为标尺绝对值；任意非零字符缩进来源均保守只读。明确 RTL、继承 RTL、run RTL 及包含 RTL 脚本族的来源也只读；混合 LTR/RTL 同样拒绝，不声称支持完整方向推断或逻辑左右缩进。

## 定向测试

- 前端初始 RED：22 项中 2 失败，分别为扩展标尺仍禁用、实际 collector 尚未识别意图。接通后先 21 通过、1 失败；失败为同一对象重复操作未被拦截，改为按同段操作总数校验后，仅重跑该 1 项通过。日志 `/tmp/word-ruler-indent-red-frontend.log`、`/tmp/word-ruler-indent-green-frontend.log`、`/tmp/word-ruler-indent-collector-rerun.log`。
- 后增原生历史和半倍缩放鼠标两项，定向 2 passed；再增宿主来源能力及重复锚点检查，定向 1 passed。当前两个标尺测试文件合计 25 项，按上述分批验证，无重复计数。日志 `/tmp/word-ruler-indent-native-gestures.log`、`/tmp/word-ruler-indent-host-reason.log`。
- 真实 DOCX 初始 RED 为缺少 inspect 能力。接通后 `test_docx_ruler_indent.py` 24 passed：直接／继承、有符号任意值、零值和边界；字符、继承字符、RTL／推断 RTL、多栏、列表、保护来源；非法字段、伪造身份、重复及同段混改。检查未知缩进属性、右缩进、pPr、run、邻段／表格、页眉／样式及非目标 ZIP 部件。最终整批计数调整并重打包后，仅重跑混改／重复 1 项通过。日志 `/tmp/word-ruler-indent-green-bridge.log`、`/tmp/word-ruler-indent-atomic-rerun.log`。
- 相关 `docx-special-indent.test.ts` 与 `docx-paragraph-format-combination.test.ts` 共 42 passed，保留字符／绝对特殊缩进与格式组合行为。日志 `/tmp/word-ruler-indent-related-format.log`。
- 未重复完整测试。

## 冻结构建与真实浏览器

冻结目录 `/tmp/word-ruler-indent-final-ecingpi1`：`static` 为前端产物，`engine/dist/edit-docx.mjs` 为独立打包桥。

- manifest SHA-256：`04b73892a52b1f16461212ac954ef6e91fe2c4cc2731b402739288b46984f010`。
- bridge SHA-256：`34f58def7008ee63d29335a5b643a8269a62c5fc68ffb2f665e25f95e3c8067a`。
- 最终 Vite 构建和全部 JS 预算通过；Word main 255560 < 256000、render 723388 < 727040、ruler 21369 字节。本批新增来源检查和意图归入既有 ruler 分包，未调整预算上限。日志 `/tmp/word-ruler-indent-vite-final.log`、`/tmp/word-ruler-indent-budget-final.log`。
- 最终 `npx tsc --noEmit` 退出 0，日志 `/tmp/word-ruler-indent-tsc-final.log`。此前记录的 `extendedIndents` 类型缺口由本批正式接入消除。

浏览器脚本 `frontend/smoke/docx-ruler-indent-smoke.mjs` 使用真实 Chromium、冻结 JS、真实 Python `patch_docx` 及冻结 Node 桥。授权和修订 HTTP 响应使用 fixture。

可编辑最终证据：`browser-editable-final/result.json`；132 个实际 JS 与冻结磁盘 SHA-256 一致，manifest／bridge 前后不变，`errors=[]`，一次真实保存。

1. 显示标尺不改正文、草稿、布局或保存状态，标尺及纸张宽度和左边位置一致。
2. 左方块键盘 +90，正文 UndoRedo 成功；首行、继承段悬挂分别真实鼠标拖动 +90。鼠标移动期间草稿／正文不变，仅在松开后提交。
3. 字符及 RTL 段显示只读原因，拒绝键盘写回；localStorage 保存两条原子操作，刷新后两段数值恢复。
4. 保存 direct 段 `left=810, firstLine=450`；继承段 `left=630, hanging=270`。独立 ZIP/lxml 验证未知缩进属性、全部 run、其余正文及非正文部件保全。只容许既有 writer 在目标 `w:t` 上添加 `xml:space="preserve"`、更新 core modified/revision 和 ZIP 目录项规范化。
5. fixture 故意返回 `validation.ok=false`；具体原因可见，实际 Word 仍下载，SHA-256 与真实保存结果相同。明确打开修订 2，两个段落的标尺值均正确；原始 DOCX 未覆盖。

首轮只读已通过，后在可编辑切换段落时因异步渲染断言抢读而失败；失败 HTML 已显示正确来源数值。改为等待标尺值／禁用状态后，仅重跑失败的可编辑流程。随后独立 XML 检查暴露上述已知 `xml:space` 规范化，用真实文件探针确认后收窄容许差异，再次仅重跑可编辑流程通过。

只读另新增真实鼠标拖动边界后定向补验：`browser-readonly-final/result.json`，132 个 JS 身份、`errors=[]`、0 保存。左／首行／悬挂三标记鼠标拖动和各标记键盘输入都不改变正文、草稿或保存状态。未为了最终汇总重跑已通过的完整套件。

已目视检查 `browser-editable-final/reopened-ruler.png` 和首轮 `browser/readonly-ruler.png`：标尺与纸张对齐，标记、正文和 Ribbon 未见裁切。

这些证据不等同生产鉴权／数据库整链、桌面 Word 或打印视觉验收。未提交、推送或部署，保留共享工作区其它改动。
