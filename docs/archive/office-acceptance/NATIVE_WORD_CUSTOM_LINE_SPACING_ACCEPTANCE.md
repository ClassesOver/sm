# Word 自定义倍数行距验收

日期：2026-11-11。固定源 `/home/junge/pros/genoffice-source-full` HEAD 本轮再次只读核对为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批在 [固定／最小行距](NATIVE_WORD_LINE_SPACING_ACCEPTANCE.md) 之后补齐自定义倍数，不代表完整段落对话框交付。

## 范围与实现

开始 → 行距 → 行距选项中的倍数改为数值输入，接受 **0.06–132 倍、0.01 精度**；范围来自固定源 `apps/docs/src/renderer/components/ParagraphDialog.tsx`。空值、非有限值、非数字、越界或超过两位小数均拒绝，保留弹窗且不修改文档。Ribbon 原有六种快捷预设不变。

复用上一批单段目标、来源身份、只读／过期选区 Guard、PM 历史、草稿、`setParagraphSpacing` 与真实 DOCX writer；生产逻辑只调整共用校验和既有弹窗，未新造写入器，也没有改发布／签发流程。切换倍数清除旧 `exact`／`atLeast` 规则和原始点值。

原生 `auto` 行距的 `w:line` 是 **1/240 行单位，不是 twips**。沿用引擎的整数换算和读取规则：0.06→14、1.23→295、4→960、132→31680；读取时恢复两位小数倍数。没有要求 OOXML 精确储存不可表示的295.2，也不修改引擎的既有舍入方式。固定／最小值继续使用 twips。

目标仍限唯一可信的原有顶层段落、标题或列表段落。表格、跨段选区、新增未保存段落与其它故事范围不扩展；完整 ParagraphDialog、特殊缩进、制表位和多级列表库仍缺。

## 测试及失败定位

- 前端 RED：新增用例使 collector 的四个自定义值和弹窗数值输入相关共10项失败、26项通过；失败分别是预设白名单拒绝与没有数值输入。
- 接通后定向运行 `npm test -- src/docx-line-spacing.test.ts src/docx-operations.test.ts src/docx-home-source.test.tsx`：行距36项、Home4项通过；collector59项中58项通过，唯一失败为旧用例要求拒绝1.2倍。该契约已按新范围更新为接受1.2、拒绝1.234，只重跑该项，通过；没有重复完整套件。日志 `/tmp/word-custom-multiple-green-frontend.log`、`/tmp/word-custom-multiple-green-collector.log`。
- Python RED：四个自定义倍数通过真实薄桥调用旧bundle均报 `docx_paragraph_spacing_invalid`。接通并重打bundle后，固定／最小值、非法输入及原始间距保全31项通过；新增四项通过了原生值和内容断言，但最终ZIP清单断言发现引擎新增目录条目。已限定比较实际文件部件集合，保留逐字节非目标部件比较；仅重跑这四项，全部通过，116 deselected。日志 `/tmp/word-custom-multiple-green-bridge.log`、`/tmp/word-custom-multiple-green-custom-bridge.log`。
- 四项真实文件测试独立验证从固定18.25pt切换为倍数、`auto`与整数原值、文字与run格式、全部非目标body XML、目标段落其它pPr、包部件集合及非目标部件字节保全。延续上一批已确认的目标 `xml:space="preserve"` 规范化排除，未扩大差异豁免。

## 最终冻结浏览器

可复用脚本：`frontend/smoke/docx-line-spacing-built-smoke.mjs`。本轮扩展原脚本，增加自定义倍数的历史／恢复／重开、非法输入、取消与Ribbon预设切回；同时保留固定／最小值回归。

冻结静态目录 `/tmp/word-custom-multiple-static-65s7_pa3/static`，manifest SHA-256 `b9d96ef5416a2132e32ec4880d1c6a4444e852a79912bb1ce28221483967162b`。Chromium `140.0.7339.16` 实际加载131个JS，逐一核对HTTP响应与冻结文件的SHA，前后manifest一致，`errors=[]`。

完整证据 `/tmp/word-line-spacing-built-DbQf8u/result.json`，四次真实Python→打包Node引擎保存及HTTP下载，逐份SHA与独立python-docx／ZIP回读通过：

| 来源→新修订 | 操作 | 独立回读 |
| --- | --- | --- |
| 1→2 | 固定18.25pt | exact / 365 twips |
| 2→3 | 最小24pt | atLeast / 480 twips |
| 3→4 | 自定义1.23倍 | auto / 295个1/240行单位 |
| 4→5 | Ribbon快捷预设1.5倍 | auto / 360个1/240行单位 |

自定义1.23倍的单次正文Undo／Redo、刷新恢复通过；明确打开修订4的弹窗显示1.23。0.05、1.234、132.01三种非法输入保持空草稿，取消不改正文；随后通过Ribbon菜单切回1.5倍并保存，明确重开修订5仍为1.5。所有下载均保留混合粗斜体、段后6pt、keepNext、其它正文／表格XML和页眉等非目标部件。

已目视检查同一冻结产物的 `custom-multiple-dialog.png` 与 `reopened.png`，输入值、说明和按钮无裁切。授权、修订仓储与发布响应为fixture，不能作为生产鉴权／DB整链、桌面Word或打印等价证明。发布fixture继续返回 `validation.ok=false` 并保留可用Word下载；本轮未触及生产签发链路。

## 构建边界

`doc_engine` 的 `npm run bundle:bridges`、前端 `npx vite build`、`npm run check:budget`、`npm run test:budget` 通过。最终Word main255351 < 256000字节、render723388 < 727040字节、行距模块3530字节；预算没有放宽。

完整 `npx tsc --noEmit` 仍有既有错误：`src/docx-ruler.test.tsx(25,54)` 的 `extendedIndents` 不属于 `Options`，记录在 `/tmp/word-custom-multiple-tsc.log`。不能声明完整npm build或全局类型检查通过。本轮未运行完整测试套件，未提交、推送或部署。
