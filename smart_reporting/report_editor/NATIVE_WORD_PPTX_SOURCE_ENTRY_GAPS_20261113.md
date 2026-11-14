# Word / PPTX 源入口核对与中文枚举修复

日期：2026-11-13。固定源只读核对：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项是限定符号链调查，不是两格式穷尽 inventory，也不代表四格式完整对齐。

后续状态：下文“PPTX 拼写检查/翻译未实现”为本次初始调查快照，已继续接通预设入口并完成真实 HTTP + Agno ScriptedModel + 引擎源码浏览器及冻结生产构建完整验证（manifest `8d4ca139…`，实际129JS）。后续 `9bd8828c…`、`6bb0f8ab…` 与最新 `0015c3b33b9184ffa601a0d60d3d501b498986b98865d7d41eb1e4f6accf3bfe` 均另做最小入口与实际129JS身份续验；逐轮归一精确资源引用文件名后，PPTX 功能代码逐字节一致，复用 `8d4` 原完整链而不重复运行。最新证据位于 `/tmp/office-word-pptx-source-gaps-20261113/ai-presets/browser-built-final-0015c3b3-identity`：画布、21语言DOM、英语当前页/拼写整稿入口通过，129实际JS响应身份全部匹配且无浏览器/HTTP错误，未启动模型job。精确范围、整稿/当前页语义和未验收边界见 `NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md`。早前固定枚举中文的证据不冒充当前冻结宿主再次交互验证，不据此更改其它未实现项。

最新构建的附带全 bundle 对照发现 `workbook-main` 与 `workbook-ribbon` 差异。`0015` 目录的 `ribbon-ast-difference.json` 进一步区分局部标识符改名与真实新增的事件/IME 守卫（`defaultPrevented`、`isComposing`、`keyCode === 229`），后者为 root 确认的外部并发变化，不能称为纯 minifier 差异。PPTX 实际129依赖不含 `workbook-ribbon`，本专项不验收该额外行为或构建后的当前工作区源码漂移；完整边界见上述验收文档。

## 本次关闭的缺口

本地 `frontend/src/slides-native-ribbon.ts` 实际以 `slidesRibbonLabel` 构造 select 的可见 option、aria-label 和 title。
此前 `slides-native-ribbon-locales.ts` 未映射以下源中文标签，导致中文界面仍显示源协议键或英文可访问名称：

| 入口 | 固定源证据 | 修复后的中文显示 | 保留的协议值 |
| --- | --- | --- | --- |
| 设计 → 幻灯片大小 | `apps/slides/src/renderer/components/Ribbon.tsx` 的 `ribbonSlideSize169/43/A4/A3` 菜单及 `i18n/ribbon/zh.ts:151–154` | 宽屏 (16:9)、标准 (4:3)、A4 纸 (210 × 297 毫米)、A3 纸 (297 × 420 毫米) | `16:9`、`4:3`、`A4`、`A3` |
| 切换 → 圆形 | 同源 `Ribbon.tsx` 转场定义 `{ kind: 'circle', label: 'ribbonTransCircle' }`；`zh.ts:320` | 圆形 | `circle` |
| 插入 → 艺术字 | 同源 `RibbonInsertTab.tsx:428–429` 的 `ribbonWordArt`；`zh.ts:249` | 艺术字（控件可访问名称及 title） | `insertWordArt`、预设 `blue` 等不变 |

生产修改只在 locale 表新增这些映射，不改引擎、写回协议、图标、源对象名称、英文模式或共享宿主。
这些功能此前已经可执行，本次只关闭具体中文显示缺口。

## 真实行为证据与测试

证据目录：`/tmp/office-word-pptx-source-gaps-20261113`。

- `locales-red.log`：新增 DOM 测试先得到 **3 失败、1 通过**，分别复现尺寸裸键、`circle` 和 `WordArt`。
- `locales-green.log`：`npx vitest run src/slides-native-ribbon-enum-locales.test.ts src/slides-native-ribbon.test.ts`，**41 通过**（新增 4、既有 Ribbon 37）。
- 新测试实际创建 `createSlidesNativeRibbon`，断言 DOM option 的 value/文字对、控件名称/title；通过真实 change 事件观察宿主边界回调，验证预设键、转场键及艺术字蓝色预设原参数不变，艺术字选择后仍复位。保留英文模式和圆形路径 SVG 的检查。
- `source-browser.mjs` / `source-browser.json`：Chromium + 隔离 Vite 源码页面真实加载同一 Ribbon，断言四个尺寸 option、圆形选中项、艺术字名称，并实际选择 A4、circle、blue，得到原始命令参数，`errors=[]`。三张 `source-*.png` 已目视检查。本层没有真实报告会话、HTTP 保存、下载或生产 bundle，不能代替 root 统一构建和冻结宿主验收。
- 源码浏览器身份：`slides-native-ribbon.ts` SHA256 `c25073f735fea30ab54dc06306203ad639733bc2e17857f9554857ce1c638dcb`；修复后 locale SHA256 `af399ff204d4395d584fdf12e5a325c8b1479e0f122c7f7597bb058604bcd092`。
- `locales-related-environment.log`：额外运行既有 `slides-layout-locales-review.test.ts` 时，该文件 2 项通过、2 项因 `slides-ruler.ts:93` 的 `ResizeObserver is not defined` 失败。此处只记录，不改无关环境，也不把这次组合执行写成全绿。

## 已交付入口与可行动的剩余边界

以下以当前源码为准，不能照旧索引把已交付的经典批注、图表图库、隐藏页、标尺/参考线或页面颜色/水印重新列作全缺。

### PPTX 审阅 → 拼写检查与翻译：预设入口已交付

2026-11-13 当前状态：整稿拼写、当前页翻译及 21 语言菜单已接既有 Agno 候选链，保留生成前授权、显式采纳、取消和过期保护；见[预设专项验收](NATIVE_PPTX_AI_PRESETS_ACCEPTANCE.md)。只保留真实 provider 翻译质量、完整源 AI 工具及该专项未覆盖的保存下载验收边界，不再列为入口缺失。普通／排序与大纲／阅读视图也已有[视图专项](NATIVE_PPTX_OUTLINE_READING_ACCEPTANCE.md)，后者限文字大纲浏览及静态逐页阅读。

以下为接线前的历史调查与当时设计，不代表当前缺口或最终授权范围；最终范围以专项的“拼写整稿／翻译当前页”为准。

- 固定源 `apps/slides/src/renderer/components/Ribbon.tsx:2455–2504`：有文稿即可打开拼写检查；用户确认后调用 `onAiPreset(t('ribbonSpellCheckPrompt'))`。翻译先显示 `TRANSLATE_TARGETS` 语言菜单，再以目标语言生成 `ribbonTranslatePrompt`，调用同一 AI 入口。
- 源 `App.tsx:3327` 将 `onAiPreset` 接到 `pushAiPreset`；该函数（约 1330 行）打开 AI 面板并登记带 nonce 的预设、autoRun 与可选授权引用。这是实际源 callback 链，不是仅有标签，也不是必须桌面 IPC 的入口。未在本次启动源桌面或真实 provider，因此不能据此声称源整链运行验收通过。
- 本地 `frontend/src/slides-native-ribbon.ts:224` 的 `spelling/translate` 仍为 `unavailable: noWrite(...)`，构造出来的按钮永久 disabled；没有翻译语言菜单或对应 action 分支。已有通用 AI 助手不能替代这些源入口。
- 本地已有可复用链：`slides-native-ai.ts` 的表单 → `api.start` → 候选预览 → 显式采纳；`slides-native-ai-context.ts::slidesAIObjects` 从当前草稿及冻结对象能力构造授权内容；后端 `slides_native_ai.py::NativeSlidesAIService` 负责预览候选与执行回执。因此这是 **源 AI 预设/目标语言入口缺口**，不能误诊成所有纯文字写回能力都不存在。
- 下一步最小接法：让 AI 面板接受“预置指令+当前页授权范围”，接通两按钮及源语言菜单；保留候选差异、显式采纳、取消、完整草稿身份守卫。源 autoRun 不应成为跳过本地候选采纳的理由。不要另建 AI agent、绕过 Agno 或默认扩大到整稿/备注。
- 验收：点击拼写检查/各目标语言时只引用授权当前页的最新草稿文字；生成前/中换页、换对象、改稿、取消或卸载不接受旧候选；候选确认前没有文件写回；确认后进入同一 UndoRedo/恢复/保存下载链；真实模型与确定性路由替身分别报告。该项本次 **未实现**。

### Word 普通／多级列表库及设置编号值：限定范围已交付

2026-11-13 当前状态：普通符号／编号库、多级列表库、自定义层级和编号值重新开始／继续／继续并前进均已交付；见[普通列表](NATIVE_WORD_LIST_LIBRARIES_ACCEPTANCE.md)、[多级列表](NATIVE_WORD_MULTILEVEL_ACCEPTANCE.md)、[编号值](NATIVE_WORD_NUMBERING_VALUE_ACCEPTANCE.md)。范围限可信原有顶层段落；无可核验定义的未保存快捷列表、图片项目符号、复杂嵌套目标和完整段落选项仍受限。

以下为接线前的历史调查，不再作为当前未实现事项：

- 固定源 `apps/docs/src/renderer/components/Ribbon.tsx` 约 4200 行：`MULTILEVEL_LIBRARY` 菜单卡片调用 `applyListPreset(levels, 'multi')`，定义按钮调用 `onListDialog('multi')`。props 同时提供 `createListDef(CustomNumberingLevel[])`；源 App 接 `onListDialog` 到实际对话框。
- 本地 `frontend/src/docx-home-source.tsx:233` 仍明确禁用 `list-multilevel-gallery`，原因是多级样式库、自定义层级及级间重新开始规则写回未接。不能把普通项目符号/编号或调整级别当成完整多级列表库。
- 后续需追源 `createListDef`、编号定义、列表段落绑定及 restart 规则的完整保存链，再设计限定协议，独立回读 `numbering.xml` 和正文绑定，验证已有列表不被重写。源 `createListDef` props 本身不是落盘完成证明；本次未改 Word。

### Word 绘图与文档主题：保留限定缺口，页面颜色/水印已排除

- 当前本地 `docx-ribbon.ts::pendingGroups.draw` 的笔/荧光笔/擦除及 `design` 的主题/字体/颜色仍走未迁移项；固定源 `Ribbon.tsx` 有 `onInkTool/onInkClearAll/onThemeFonts/onThemeColors` props 并传入对应组件。后续必须继续跟源宿主和保存模型，不按 props 一概算完整持久化能力。
- 同一本地文件已对 `design` 的页面颜色和水印单独接真实 controller（`page-color` / `watermark` 分支），本次明确不将它们列为缺功能。这个修正避免复用早期索引“整个 Design 都缺”的过宽结论。

未改共享 `main.ts/native-main.ts/native-ai*.py/app.py`、工作簿/PDF、统一 audit、SOURCE/hash 或生产 static；未完整测试、提交、推送或部署。
