# Word 绝对特殊缩进增量验收

日期：2026-11-11。固定 GenOffice 来源：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

后续增量：首行字符单位输入已接通并另行验收，见 [字符首行验收](NATIVE_WORD_CHARACTER_INDENT_ACCEPTANCE.md)。下文保留本批绝对点值阶段的范围和证据。

## 范围和实现

开始 → 行距 → 特殊缩进，支持唯一可信原有顶层普通正文段落或标题的“首行／悬挂／无”。首行和悬挂支持 0.05–720 pt，精度 0.05 pt；协议为有符号整数 twips，范围 −14400..14400，正数首行、负数悬挂、零取消。取消缩进显式写入零，避免重新继承来源样式的特殊缩进。

沿用固定源 ParagraphDialog 的绝对特殊缩进子能力，复用本地 Modal、焦点约束、PM 历史与草稿链路，新增 `setParagraphSpecialIndent`，前后端共用数值校验。原生写回复用 `mergeCellParaFormat`，保留左右缩进及其字符单位属性；仅将特殊缩进的 `firstLineChars`、`hangingChars` 显式归零，覆盖直接和样式继承的字符特殊缩进。来源为字符单位时显示当前换算点值并说明确定后转换；取消保持来源原样。

一次确定是一个撤销步骤；取消、非法输入不修改正文或草稿。弹窗打开后文档、选区或只读状态改变时拒绝确认。沿用已有保存 Guard，对不兼容的混合编辑提示先保存。草稿回放检查字段、原对象身份、编辑能力和数值。

本批不含字符单位输入、标尺拖动、列表／表格／跨段选区、新增未保存段落、页眉页脚或文本框目标，也不代表完整 ParagraphDialog、多级列表或制表位已对齐。

## 定向测试

- 前端初始 RED：新增22项中15失败、7通过，失败对应缺失的入口和协议；接通后22项全部通过。覆盖 collector/replay、真实 Ribbon、三种类型、单步 UndoRedo、非法输入、字符来源取消、文档／选区／只读变化、伪造身份和列表恢复拒绝。
- 相关前端组合运行：`src/docx-special-indent.test.ts src/docx-operations.test.ts src/docx-line-spacing.test.ts src/docx-home-source.test.tsx`，118通过、3个旧断言失败。旧断言把已经建模的特殊缩进当作未知属性；更新为验证左缩进和特殊缩进共同采集，并保留 `keepLines` 未支持属性拒绝后，只复跑这3项，全部通过。合计覆盖121个不同用例，未再次运行完整组合。
- 附加边框／底纹组合及清除格式回归：初次9通过、1个旧组合断言失败。该测试将现有对齐／左缩进／间距也当作不支持；改为验证各自与装饰格式的正反顺序回放，新增特殊缩进组合，保留样式混用、分页混用、未知属性、字符混用、重复操作、只读和伪造身份拒绝。首次回放发现测试输入缺少 `spaceBeforeAuto:null`，按真实间距协议补齐后，仅复跑该1项通过。其余9项未重复执行。
- Python 初始 RED 为操作类型未支持；接通后 `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_docx_special_indent.py -x`：16 passed。10项真实往返覆盖直接／继承字符来源与365、−480、0、±14400 twips；6项拒绝越界、小数、空值、布尔和字符串。
- 通过 python-docx 与独立 ZIP/XML 回读，验证原文、混合 run 格式、左右缩进及字符属性、目标段落其他 pPr、非目标 body（含表格）、页眉、样式及其他非目标包部件。仅排除既有目标 `w:t` 的 `xml:space="preserve"` 规范化与允许更新的 core 属性；ZIP 比较忽略目录条目，不忽略实际文件部件。

## 冻结构建真实浏览器

复用 `frontend/smoke/docx-line-spacing-built-smoke.mjs`，以 `DOCX_TEST_SPECIAL_INDENT=1` 选择特殊缩进模式；原行距模式保留。冻结资产 `/tmp/word-special-indent-static-6402fgcy/static`，manifest SHA-256：

`4b0b68661f4ac7077288e6adbbc65130772ad51b714c62f22df817ec237a4465`

Chromium `140.0.7339.16`，实际加载132个JS响应，逐个核对冻结字节身份，前后manifest一致，`errors=[]`。结果 `/tmp/word-special-indent-built-WZGvI2/result.json`；运行日志 `/tmp/word-special-indent-browser.log`。

1. 来源直接 `firstLineChars=200`、样式继承 `hangingChars=100`，界面读取换算值24pt并显示转换提示。取消和非法0／720.05／18.123均不写草稿。
2. 首行18.25pt → 365twips，正文 Ctrl+Z／Redo、刷新恢复草稿通过。
3. 修订1→2首行365，修订2→3悬挂−480，修订3→4取消0，共三次实际 Python→打包Node桥保存；HTTP下载SHA与独立DOCX回读全部通过。
4. 明确打开修订2／3时读到前次首行／悬挂原值，修订4读到“无”，正文一致；左右缩进与字符属性、行距、段后、keepNext、表格、页眉、样式及非目标包部件保全。
5. `character-source-dialog.png` 与 `reopened.png` 已目视检查，弹窗、提示、按钮及重开正文未见裁切。

边界：授权、修订登记和发布响应使用fixture；不代表生产DB／鉴权整链、桌面Word或打印等价验收。fixture返回 `validation.ok=false`，仍提供并成功使用Word下载链接；本批未修改生产发布／签发链路。

## 构建与检查限制

`doc_engine` 的 `npm run bundle:bridges`、前端 `npx vite build`、`npm run check:budget` 与 `npm run test:budget` 通过。特殊缩进弹窗单独分包3260字节；冻结Word main255847 < 256000字节、render723388 < 727040字节；未提高阈值。

完整 `npx tsc --noEmit` 未通过：既有 `src/docx-ruler.test.tsx(25,54)` 的 `extendedIndents` 不属于 `Options`，以及工作区 `src/slides-geometry-pane.test.ts(2,42)` 缺少 `./slides-geometry-pane` 模块。日志 `/tmp/word-special-indent-tsc.log`。不声明全局类型检查或完整测试通过。

仅执行专项及失败用例的定向复跑；未重复完整测试，未提交、推送或部署。共享工作区其他改动保留。
