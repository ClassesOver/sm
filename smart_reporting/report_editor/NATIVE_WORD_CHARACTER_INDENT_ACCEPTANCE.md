# Word 首行字符单位增量验收

日期：2026-11-11。固定源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。承接 [绝对特殊缩进验收](NATIVE_WORD_SPECIAL_INDENT_ACCEPTANCE.md)。

## 功能与边界

开始 → 行距 → 特殊缩进增加 pt／字符选择。唯一可信原有顶层普通正文／标题单段的首行可输入0.01–100字符、精度0.01字符，按字号计算的twips后备值仍受0..14400限制。来源直接首行字符值打开时显示原单位和原值；取消不改变文档。切换单位沿用固定源的默认播种规则：字符为2字符、绝对值为36pt，用户可继续修改。

复用现有 `setParagraphSpecialIndent`，新增可选 `firstLineChars`（1..10000的整数百分之一字符）。绝对模式请求保持原形；字符模式同时携带非负twips后备值，正负混用、空值、布尔、字符串、超范围或小数原生字符值均拒绝。共享validator同时用于UI、collector、草稿回放和Node桥；来源身份、只读和列表目标检查继续保留。

后备点值取段首文本run字号，依次考虑字符样式、空段字号、段落样式、文档默认字号，不依赖光标落在哪个run。原生 `w:firstLineChars` 是权威值；原生引擎仍按自身的字号、字距、字符网格规则解析，后备点值不替代字符单位。写回继续复用 `mergeCellParaFormat`，保留左右缩进及其字符属性；显式归零 `hangingChars`，避免继承悬挂覆盖首行字符值。切换绝对首行、悬挂或取消时归零两类特殊字符属性，保留其余pPr。

一次确定对应一次UndoRedo，保留草稿刷新恢复、陈旧选区／文档／只读状态拦截。固定源 `components/paragraph-special-indent.ts` 和 `ParagraphDialog.tsx` 自身仅对首行建模字符输入，悬挂切回绝对单位；本地遵循这个边界，不将字符悬挂记为已完成。本批也不开放标尺拖动、列表／表格／跨段选区、新增未保存段落、页眉页脚或文本框目标。

## 测试记录

- 前端初始RED：37项中8失败、29通过，失败来自缺少字符输入和源字符值显示能力；非法草稿用例在旧协议下已被拒绝。接通后同37项全部通过，覆盖原生字符采集／回放、真实Ribbon、段首12pt／光标20pt的混合run后备值564、单步UndoRedo、来源取消与非法输入。日志 `/tmp/word-character-indent-red-frontend.log`、`/tmp/word-character-indent-green-frontend.log`。
- 后增段落样式18pt换算846及切悬挂清字符用例，仅运行该1项通过（其余37跳过）；日志 `/tmp/word-character-indent-style-fallback.log`。当前文件38项，分两次验证，不重复相加。
- 相关组合：`src/docx-paragraph-format-combination.test.ts src/docx-line-spacing.test.ts`，40 passed。日志 `/tmp/word-character-indent-format-regression.log`。
- Python初始RED：首个有效字符请求被旧Node桥字段检查拒绝。接通后专项30 passed（含上一批16项绝对缩进），覆盖直接／继承字符来源、百分之一字符值1／235／6000、左右缩进与字符属性、切换取消、原文和非目标包部件保全、8类无效字符请求。日志 `/tmp/word-character-indent-red-bridge.log`、`/tmp/word-character-indent-green-bridge.log`。
- 后增真实引擎字体重解析用例单独1 passed、30 deselected：保存首行2.35字符后，仅将首个run从12pt改18pt，再用实际 `parseDocx` 读取，缩进从564变846twips。未把XML字段存在当成字号联动成功。日志 `/tmp/word-character-indent-font-reparse.log`。当前Python文件31项，未重新完整执行。

## 冻结构建浏览器

复用 `frontend/smoke/docx-line-spacing-built-smoke.mjs`，增加 `DOCX_TEST_CHARACTER_INDENT=1` 模式，保留绝对特殊缩进和行距模式。资产 `/tmp/word-character-indent-static-hgf62ax7/static`，manifest SHA-256：

`536892de4c2ef16e87911af20aaac10f4a1386b578204908ee2c279d7ee866c5`

Chromium `140.0.7339.16`，132个实际JS响应逐个与冻结文件核验身份，前后manifest一致，`errors=[]`。结果 `/tmp/word-character-indent-built-2IsRwR/result.json`。

1. 来源2字符按字符单位读取；取消、非法0／100.01／2.345／61（12pt下后备值超上限）均不产生草稿。
2. 设置2.35字符，草稿为 `twips:564, firstLineChars:235`；正文Ctrl+Z／Redo和刷新恢复同时保留两个字段。
3. 修订1→2字符首行2.35；2→3绝对首行18.25pt；3→4悬挂24pt；4→5取消。四次实际Python→打包Node桥保存、HTTP下载SHA和独立python-docx／ZIP属性回读通过。
4. 明确打开修订2、3、4、5，分别读到字符2.35、pt18.25、悬挂pt24、“无”；左右缩进及字符属性、目标其他pPr、原文与run、非目标body／表格／页眉／样式及其他包部件保全。
5. `character-source-dialog.png` 与 `reopened.png` 已目视确认，单位控件、提示、按钮和重开正文未见裁切。

授权、修订登记和发布响应使用fixture，不冒充生产DB／鉴权整链、桌面Word或打印验收。fixture故意返回 `validation.ok=false`，Word下载仍成功；本批未修改生产签发链路。

## 构建与全局限制

Node桥 `npm run bundle:bridges`、前端 `npx vite build`、`npm run check:budget` 通过。冻结Word main255847 < 256000字节、render723388 < 727040字节；特殊缩进分包4733字节，未抬预算阈值。

本次 `npx tsc --noEmit` 仅报告既有 `src/docx-ruler.test.tsx(25,54)` 的 `extendedIndents` 不属于 `Options`；日志 `/tmp/word-character-indent-tsc.log`。上批曾同时出现的Slides缺模块错误本次未出现，不据此认定本批修复了它。完整类型检查仍未通过。未重复完整测试、提交、推送或部署；保留共享工作区其他改动。
