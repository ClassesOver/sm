# PPTX 动画窗格 / 无 / 按段 / 动作路径验收

2026-11-10。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 PPTX Ribbon 已全部对齐。

## 固定源行为

- `apps/slides/src/renderer/animation-actions.ts`：所有动画动作最终都调用 `commitAnimations`，把当前页的整份动画列表覆盖写回（`setAnimations`）。
  - `applyAnimation('none')`：移除所选对象的全部动画。
  - `applyMotionPath`：在列表末尾追加一条动作路径动画，默认时长 2000ms。
  - “按段”开启后，对多于 1 段的文字对象，每段各生成一条动画；动作路径不拆分。
  - `patchAnimTiming` / `moveAnimation` / `deleteAnimation`：对窗格选中的条目改计时、上移下移、删除。
- `components/Ribbon.tsx` `MOTION_PATHS`：右直线、下直线、对角线、圆形、锯齿五条预设路径，坐标相对幻灯片宽高。
- `components/AnimationPane.tsx`：按顺序列出当前页动画，显示步骤编号（单击触发递增）、效果、目标对象和段落。
- 引擎 `pptx-engine/src/animation.ts`：`setSlideAnimations` 支持 `motionPath` 与 `paragraph`（写成 `pgRg`）；无法建模的预设效果以 `presetXml` 原样保留。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `editSlides.animationSequences: [{slideIndex, items}]`。条目分两种：`{source, spid, effect, trigger?, durationMs?, delayMs?}` 引用来源文件已有的动画；其余字段的条目为新增动画（可带 `direction`、`motionPath`、`paragraph`）。 |
| 前端 | Animations 选项卡的“None”“Animation Pane”“By Paragraph”和五条 Motion Paths 均已启用。窗格显示在右侧对象面板顶部，可选中、上移、下移、删除；选中一条后，“Timing”组的触发方式、时长、延迟直接修改该条。 |
| 桥接 | 逐条校验后调用固定引擎未改动的 `setSlideAnimations`。`source` 条目必须与来源动画的序号、`spid`、效果一致，且每条只能引用一次；新增条目只接受 20 种可写效果和五条预设路径，段落序号须在对象段落数以内。 |
| 兼容 | 原有逐条写法（`animations`）继续可用。某页第一次做整页编辑时，该页尚未保存的逐条修改会折叠进序列；同一页两种写法并存时桥接拒绝。 |

## 与固定源的差异

- **预设效果的计时**：原样保留的预设效果（`presetXml`）只能移动或删除。它的计时写在原始 XML 里，改了也不会生效，所以前端禁用、桥接拒绝，而不是假装成功。
- **计时控件的绑定**：固定源在没有选中窗格条目时，会把计时改到所选对象的最后一条动画上。这里未选中条目时，计时控件只作为下一条新增动画的参数，以保持原有“先设计时再添加”的流程。
- **动画预览**：仍未接通，浏览器端没有动画播放器。
- **新增页**：保存重开前没有可寻址对象，不能编辑动画。

## 证据

- `reporting/tests/test_slides_engine_bridge.py`：
  - 真实 PPTX 上重排、删除、改计时，并追加锯齿路径和三段飞入；回读顺序、计时、方向、段落一致，XML 中有 `pgRg` 与 `animMotion`。
  - 空列表清空整页动画。
  - 12 种非法序列（来源身份不符、重复引用、越界段落、未知路径、媒体效果等）均被拒绝且不产生输出；同页两种写法并存、保留已删除对象的动画也被拒绝。
- `reporting/tests/test_native_office.py`：经 Python 入口写入并回读；结构非法的序列返回错误。
- `frontend/src/slides-animation-sequence.test.ts`、`slides-native-ribbon.test.ts`。
- `frontend/smoke/pptx-native-save-smoke.mjs`（`PPTX_SMOKE_MODE=animation-pane`）：在 Chromium 中跑真实的 Python→PPTX 引擎链路，授权和修订路由用 fixture。来源文件自带淡入和缩放两条动画。步骤：
  1. 打开窗格，显示两条。
  2. 选中正文点“None”，剩一条。
  3. 开启“By Paragraph”，添加自左飞入，正文两段各生成一条。
  4. 给另一对象添加锯齿路径。
  5. 在窗格中把路径上移一位；选中缩放，改为“与上一动画同时”、1200ms；删除最后一条。
  6. 撤销、重做后条数正确。
  7. 保存为修订 2，下载后重开回读：缩放为同时/1200ms，正文第 1 段自左飞入，另一对象沿锯齿路径，原淡入已移除。
- 原有 `transitions-animations` 冒烟模式同时复跑通过。

本次在开发服务器模式下运行。生产镜像、真实授权和发布链路没有在本次验收范围内；也没有在 PowerPoint 中打开输出文件做人工播放核对。
