# PPTX 新建幻灯片验收

2026-11-09。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。单项命令闭环，不代表 PowerPoint Ribbon 全功能对齐。

## 固定源行为

- `apps/slides/src/renderer/slide-actions.ts` `addSlide(ctx)`：`slidesApi.addBlankSlide({ sourceIndex: ctx.current })`，新页插在当前页之后并成为当前页。
- 主进程 `{ op: 'addBlankSlide', target: { slide } }` → `packages/pptx-ops` → `pptx-engine` `insertBlankSlide(opened, sourceIndex)`：
  空白 `p:sld`，沿用来源页的 slideLayout 关系。Home ▸ Slides 与 Insert ▸ Slides 的 New Slide 均调用 `onAddSlide`。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 草稿 | `editSlides.newSlides: [{ layoutFrom }]`；新页 k 的索引为 `来源页数 + k`，`order`（长度 = 来源页数 + 新页数）决定位置 |
| 桥接 | `bridge/edit-pptx.ts` 在所有按来源索引寻址的步骤之后调用固定引擎 `insertBlankSlide(layoutFrom)` 再移到末尾，来源页索引保持不变，随后按 `order` 重排；校验 ≤50、`layoutFrom` 为来源页、字段严格、必须带 `order` |
| 服务 | `native_office.py` 同样严格校验后才调用引擎；`slides.py` 透传 `newSlides` |
| 前端 | Ribbon Home/Insert 两个 New Slide 启用（保留 `onAddSlide` 身份）；当前页之后插入、选中新页；新页沿用当前页（或其版式来源）版式；列表显示“新建幻灯片（保存后写入）”并可移除；可上移/下移；草稿刷新恢复 |
| 边界 | 新页保存重开前不接受文字、背景、版式、转场、动画、文本框等页面/对象修改（界面禁用或提示原因，引擎按来源页数拒绝）；有新页时不采纳 AI 页面修改、不能统一应用转场 |

## 证据

- `reporting/tests/test_slides_engine_bridge.py`：真实引擎两张新页分别沿用第 3 页/第 1 页版式、无对象、按 order 落位；同批按索引的转场仍作用于原第 2 页；python-pptx 独立读取页数；非法来源、多余字段、缺少/不完整 order 均拒绝且不产生输出。
- `reporting/tests/test_native_office.py`：服务路径往返与非法 `newSlides` 不调用引擎。
- `frontend/src/slides-native-ribbon.test.ts`：Home/Insert New Slide 启用、来源动作身份、派发 `addSlide`、锁定时禁用。
- `frontend/smoke/pptx-native-save-smoke.mjs`（`PPTX_SMOKE_MODE=new-slide`，Chromium + 真实 Python→PPTX 引擎，授权/修订路由为 fixture）：新建 → 再新建并移除 → 上移到首页 → 刷新恢复 → 保存修订 2 → 下载身份一致 → python-pptx 独立回读两页（首页空白、版式与原页相同、原文字保留）→ 重开修订 2 新页成为普通页。原 `textbox` 模式回归通过。

生产镜像、真实授权与发布链路未在此验收。
