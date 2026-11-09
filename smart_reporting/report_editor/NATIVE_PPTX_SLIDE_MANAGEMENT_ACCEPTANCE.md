# PPTX 新建 / 指定版式新建 / 复制 / 删除幻灯片验收

2026-11-09。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。单项命令闭环，不代表 PowerPoint Ribbon 全功能对齐。

## 固定源行为

- `apps/slides/src/renderer/slide-actions.ts` `addSlide(ctx)`：`slidesApi.addBlankSlide({ sourceIndex: ctx.current })`，新页插在当前页之后并成为当前页。
- 主进程 `{ op: 'addBlankSlide', target: { slide } }` → `packages/pptx-ops` → `pptx-engine` `insertBlankSlide(opened, sourceIndex)`：
  空白 `p:sld`，沿用来源页的 slideLayout 关系。Home ▸ Slides 与 Insert ▸ Slides 的 New Slide 均调用 `onAddSlide`。

## 新建指定版式幻灯片（固定源 onAddSlideWithLayout）

- Home ▸ Slides 的 New Slide with Layout 为版式选择器（打开后由 `setLayouts` 填入演示文稿版式，选后复位）；新页插在当前页之后。
- 草稿 `newSlides` 项 `{ withLayout: 版式路径 }`；桥接校验版式在包内后调用固定引擎 `insertSlideWithLayout`（生成版式占位符）并放在末尾，再由 `order` 落位；Python 端校验路径格式（拒绝 `..`、非版式路径、盘符）。

## 重置版式（固定源 onResetLayout → resetSlideLayout）

- Home ▸ Slides ▸ Reset Layout 作用于当前来源页，进入待保存清单（可单独撤销）。
- 草稿 `resetLayouts: [来源页]`；桥接最先调用固定引擎 `resetSlideLayout`（占位符去掉显式 xfrm，回到版式/母版继承位置），同批其他修改叠加在重置后的页面上。新建页不适用；已加入重置的页不能再复制或删除（与其他待保存修改一致）。
- 证据：`test_slides_bridge_reset_layout_restores_inherited_placeholder_geometry`（移位标题回到继承几何、文字保留，非法索引无输出）、Ribbon 单测、`new-slide` 冒烟中重置并保存。

## 形状填充与轮廓（固定源 Shape Format ▸ Shape Styles / setFill · setStroke）

- 选中形状或文本框时出现的 Shape Format 上下文标签：填充颜色、无填充、轮廓颜色、轮廓粗细（0.75–6 磅，同 PowerPoint 档位）、无轮廓；每个对象的修改合并为一条待保存项，可单独撤销；删除对象时一并撤回其样式。
- 草稿 `shapeStyles: [{slideIndex, elementId, fill?, stroke?}]`；桥接用固定引擎 `setElementFill` 与 `strokePatchToModel` 写入，拒绝非法颜色、零线宽、空修改、已删除或不存在的对象。
- 证据：`test_slides_bridge_sets_shape_fill_and_outline`、Ribbon 单测、`new-slide` 冒烟为文本框设置绿色填充与 3 磅轮廓并核对 XML。

## 插入表格（固定源 Insert ▸ Table / table-insert.ts）

- Insert ▸ Tables ▸ Table 打开行列对话框（默认 5 列 × 2 行，1–75），表格进入待保存清单。
- 几何与固定源 `tableInsertSpec` 一致：宽为幻灯片 2/3 并水平居中、顶部在 10.5% 高度、每行 29.2pt；桥接按演示文稿尺寸计算后调用固定引擎 `addTable`（默认表格样式）。`addTable` 会把已做修改写入 XML 后重建页面并改变对象身份，因此在全部按对象身份的修改（改字、样式、删除等）与尺寸缩放之后最后执行，同页同批修改均生效（`test_slides_bridge_table_coexists_with_element_edits_on_the_same_slide`）。
- 证据：`test_slides_bridge_inserts_table_with_pinned_geometry_alongside_other_edits`、Ribbon 单测、`new-slide` 冒烟插入 4×3 表格并用 python-pptx 回读行列。

## 页码与日期字段（固定源 insertField）

- Insert ▸ Text ▸ Slide Number / Date and Time：与固定源相同，在页面中央新增文本框（页码 100×44、日期 240×44，18pt，居中），内容为 `<a:fld type="slidenum|datetime1">` 动态字段，缓存值为当前页码或今日日期，PowerPoint 打开时刷新。
- 复用新增文本框通道（`textBoxes[].field`），桥接与 Python 只接受 `slidenum`、`datetime1`。
- 证据：`test_slides_bridge_inserts_slide_number_and_date_fields`、Ribbon 单测、`new-slide` 冒烟插入页码字段并核对 XML。

## 插入形状（固定源 Insert ▸ Shapes / onPickShape）

- Insert ▸ Illustrations ▸ Shapes 为分组选择器：固定源 `SHAPE_GALLERY_GROUPS` 7 组 109 个预设，中文名称取自固定源语言包（`components/shape-gallery-data.ts`，来源与哈希见 `SOURCE.md`）。选后复位，形状加入待保存清单（可单独撤销）。
- 插入默认值与固定源一致：普通形状填充 `#C43E1C`（`default-shape.ts` 出厂样式），线条类为 1pt 黑色连接符（`insert-actions.ts`）；初始位置居中、宽 30%。
- 草稿 `shapes: [{slideIndex, kind, geometry}]`；桥接与 Python 只接受同一份 109 项白名单（`bridge/shape-presets.json`，测试保证与前端数据一致），交给固定引擎 `addElement`。画布在保存重开后显示新形状（与新增文本框一致）。
- 证据：`test_slides_bridge_inserts_gallery_shapes_with_pinned_default_styles`、`test_bridge_shape_allow_list_matches_frontend_gallery`、Ribbon 单测（7 组 109 项）、`new-slide` 冒烟插入圆角矩形与箭头并核对保存的 XML。

## 复制幻灯片（固定源 duplicateSlide）

- 草稿 `newSlides` 项为 `{ duplicateOf: 来源页 }`；桥接调用固定引擎 `duplicateSlide` 后移到末尾，再由 `order` 落位。
- 复制的是来源页**已保存内容**：桥接在任何其他修改之前创建全部新页（追加到末尾，编号不变），因此同批对来源页的修改（文字、转场、表格、形状等）只作用于来源页、不进入副本；复制时来源页已有待保存修改则前端提示先保存。副本在保存重开前只读。

## 删除幻灯片（固定源缩略图 deleteSlide）

- 草稿 `editSlides.deletedSlides: [来源页索引]`，`order` 只列保留页（原始编号 = 来源页 + 新建页）。
- 桥接在新建页插入之后按部件路径调用固定引擎 `deleteSlide`；拒绝重复/越界、删除全部页、`order` 含已删页，以及同批仍引用被删页的任何修改或被新建页沿用版式。
- 前端每个来源页行提供“删除幻灯片”；该页有待保存修改、被新建页沿用版式或仅剩一页时拒绝并说明原因；撤销/草稿恢复按同一校验。

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
- 指定版式：`test_slides_bridge_adds_slide_with_chosen_layout_placeholders`、`test_real_pptx_new_slide_with_layout_and_path_validation`、Ribbon 版式选择器单测。
- 复制：`test_slides_bridge_duplicates_saved_slide_content_and_rejects_pending_edits_on_source`。
- 删除：`test_slides_bridge_deletes_source_slides_with_new_slides_and_order` 与 6 个拒绝用例；`test_real_pptx_slide_deletion_roundtrips_and_rejects_invalid_requests`。
- `frontend/smoke/pptx-native-save-smoke.mjs`（`PPTX_SMOKE_MODE=new-slide`，夹具两页；Chromium + 真实 Python→PPTX 引擎，授权/修订路由为 fixture）：新建 → 再新建并移除 → 删除被沿用版式的来源页被拒绝 → 删除另一来源页 → 上移到首页 → 复制来源页（副本只读、显示原内容）→ 按 Title Slide 版式新建 → 刷新恢复 → 保存修订 2 → 下载身份一致 → python-pptx 独立回读四页（末页版式为 Title Slide；首页空白且版式与原页相同、原文字保留、副本与原页一致、被删页不存在）→ 重开修订 2 新页成为普通页。原 `textbox` 模式回归通过。

生产镜像、真实授权与发布链路未在此验收。
