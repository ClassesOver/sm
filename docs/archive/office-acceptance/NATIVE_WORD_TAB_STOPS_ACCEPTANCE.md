# Word 标尺制表位增量验收

日期：2026-11-11。固定 GenOffice 源 HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。承接 [标尺缩进验收](NATIVE_WORD_RULER_INDENT_ACCEPTANCE.md)。

## 交付与边界

复用固定源 `Ruler.tsx`：在 100% 页面缩放、可信原有顶层普通正文／标题单段上开放制表位类型选择、点击新增、鼠标移动／拖出删除、键盘微调和 Delete／Backspace 删除。选择器沿用 left／center／right／decimal／bar 五种类型，切换类型不改正文或草稿。已有受支持引导符在移动及保存时保留，本批未增加引导符编辑对话框。

来源须为单栏、非镜像、无非零字符缩进、LTR，且普通编辑能力有效。列表／表格／跨段、新增未保存段、页眉页脚、文本框、RTL／混合RTL、相对定位 `w:ptab`、未知或歧义的制表位 XML 继续只读。直接属性及样式链中的 `w:tabs` 均校验，不把解析器对未知值的降级当成可逆来源。未知属性留在原文件，不强行改写。

固定源制表位鼠标逻辑使用未缩放宽度，而缩进标记已采用屏幕宽度，两者不同；本批不更改 vendor。非 100% 时整个制表位编辑显示明确只读原因，恢复 100% 后重新开放。此边界不是完整 Word 制表位或完整 ParagraphDialog 对齐。

新增 `setParagraphTabStops`，只接收 `stops` 数组，每项为整数 twips `pos`、受支持 `val` 和可选 `leader`。拒绝显示专用 inherited／rel、额外字段、重复位置、无效类型和值。范围 −31680..31680 twips、最多128项；数组排序后持久化，空数组代表清掉直接制表位。UI 沿用源 60 twips 微调／吸附及 Shift 720 twips 规则。

源 `directTabStops` 将继承制表位直接化，并为删除／移动的继承位置添加 `clear`。collector 保留显式意图，草稿严格回放，后端再次核验来源身份和能力；同段正文／其它格式混改及重复操作原子拒绝，要求先保存。每次提交独立 UndoRedo，连续手势合为同段一条保存操作。Node 复用既有 `mergeCellParaFormat`，没有另造 OOXML writer，未改变发布签发链路。

## 测试记录

- 前端初始 RED：制表位仍禁用。接通后 `docx-tab-stops.test.ts` 3 项和当时 `docx-ruler.test.tsx` 21 项全部通过，日志 `/tmp/word-tabs-green-ui.log`。覆盖实际 collector／回放、显式空意图、继承 clear、非法协议、过期身份、只读及同段混改／重复。
- 后增原生键盘／独立历史和鼠标两项。接入测试宿主真实扩展及回调后键盘1项通过；鼠标用例因未等待 React 类型状态先失败，修正等待后单项通过。当前文件23项，加纯意图3项，合计26项按分批验证。日志 `/tmp/word-tabs-red-native.log`、`/tmp/word-tabs-green-native.log`、`/tmp/word-tabs-native-click-rerun.log`。
- 浏览器发现真正的宿主事件错误：类型按钮被当拖动，mouseup 重建源组件后类型回到 left。补完整 pointer 事件回归先失败，修复为仅在真实拖动标记 mousedown 建快照；类型按钮及背景点击不建拖动快照。仅重跑该项与相关拖动取消／缩放回归9项通过，日志 `/tmp/word-tabs-pointer-cycle-red.log`、`/tmp/word-tabs-pointer-cycle-green.log`。
- 真实 DOCX `test_docx_tab_stops.py`：首次因缺少 inspect 能力 RED；接通后22项通过、1项保护夹具失败。夹具只给 enforcement 而未给 edit，源解析器将其视为无保护；补 `w:edit="readOnly"` 后仅重跑保护1项通过。当前23项均分批通过，日志 `/tmp/word-tabs-green-docx.log`、`/tmp/word-tabs-protected-rerun.log`。覆盖直接／继承、五种类型、引导符、clear、清掉最后一项、未知来源、RTL／分栏／镜像／保护／相对定位、非法协议、过期身份及批次冲突。
- 既有标尺缩进意图5项及段落格式组合4项，共9项相关回归通过，日志 `/tmp/word-tabs-related-regression.log`。
- 未运行或重复完整测试。

## 冻结构建与浏览器

冻结目录 `/tmp/word-tabs-final2-7lcqta5d`，前端 `static`，引擎 `engine/dist/edit-docx.mjs`。

- manifest SHA-256：`19f1975e3ec9add1e080b509fb2caa884609cf4de7dfeb66f67654a34698580d`。
- bridge SHA-256：`870bf8460d5cac896e2a25c59c35c4714361fd3783bf768cb54bb3967d363844`。
- Vite 构建、全部 JS 体积预算通过。Word main255629 < 256000、render723388 < 727040、ruler24374字节；新增模块进入既有 ruler 分包，未抬阈值。日志 `/tmp/word-tabs-vite-final.log`、`/tmp/word-tabs-budget-final.log`。
- 本次完整 `npx tsc --noEmit` 未通过：仅报告共享工作区 `src/pdf-form-canvas.test.ts` 两处 TS2783，`sourceSha256` 重复定义；不在本批修改范围。首次日志 `/tmp/word-tabs-tsc.log`；鼠标捕获修复后的最终检查 `/tmp/word-tabs-tsc-final.log` 同样仅报告这两处错误，退出2。本批没有修复或忽略这些错误，不把 Vite 成功说成全局类型检查通过。

`frontend/smoke/docx-tab-stops-smoke.mjs` 使用真实 Chromium、冻结 JS、真实 Python `patch_docx` 与冻结 Node 桥。最终 `browser/result.json`：只读／可编辑两模式、132个实际加载JS逐一核对冻结身份、manifest及bridge前后不变、`errors=[]`，一次真实保存，两条操作。

1. 显示尺规和五种类型循环不写正文／草稿；只读键盘、鼠标拖动和背景新增均无写回。
2. 直接段 left2160→2220，真实 Ctrl+Z／Redo；right4320→4500 实际鼠标拖动，移动期间不写入；点击新增 decimal5760。原 dot／hyphen 引导符保留。
3. 继承段 left2880 拖出删除；实际草稿为 `[{pos:2880,val:'clear'}]`，刷新恢复后没有标记；未知属性及 RTL 来源拒绝编辑。
4. 保存捕获真实两条 `setParagraphTabStops`，交由 Python／Node 实际写回。独立 ZIP/lxml 核对上述制表位及 clear，保留原文、run、其余 pPr、邻段／表格、页眉／样式及其它部件；只容许既有目标 w:t 的 `xml:space="preserve"` 添加、core modified／revision 更新和 ZIP 目录项规范化。
5. fixture 返回 `validation.ok=false` 及具体原因，真实 Word 下载仍成功；下载 SHA 与保存文件相同。明确重开修订2，直接段三标记正确，继承位没有复现，原始 DOCX 未覆盖。

新增缩放边界后，仅运行 `DOCX_TABS_CASE=zoom`：`browser-zoom/result.json`，132个JS身份一致，`errors=[]`，0保存。110%禁用类型／标记并显示100%提示，键盘和鼠标不改变草稿；恢复100%后重新开放。未重复已过的保存套件。

已目视检查 `browser/reopened-tabs.png` 和 `browser/readonly-tabs.png`，标尺、纸张与 Ribbon 未见裁切。授权、修订登记及验收响应使用 fixture；本批证据不等同生产鉴权／数据库整链、桌面 Word 或打印视觉验收。未提交、推送或部署，保留共享工作区其它改动。
