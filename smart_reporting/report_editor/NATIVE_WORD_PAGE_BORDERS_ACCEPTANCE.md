# Word 设计 ▸ 页面边框验收

2026-11-13。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项命令闭环，不代表 Word 功能区已全部对齐。

## 固定源行为

- `ribbon-design-tab.tsx`：设计 ▸ 页面背景 ▸ 页面边框，下拉菜单含“方框（单实线）”“无”“页面边框…”。前两项经 `onPageBorderAll` 作用于全部节。
- `PageBorderDialog.tsx`：
  - 设置：无、方框、阴影、三维、自定义。
  - 线型 24 种，颜色含“自动”，宽度 9 档，艺术型 170 种（宽度 1–31 pt）。
  - 在预览中点击可开关单边。
  - 应用于：整篇文档、本节、本节-仅首页、本节-除首页外所有页。
  - 选项：四边距离、测量基准（文字或页边）、总在前面显示。
- 引擎 `packages/docx-engine/src/section.ts`：
  - `applySectionSettings` 根据节设置 `pageBorder` / `pageBorderProps`，经 `pageBordersXml` 改写 `w:sectPr/w:pgBorders`。
  - `pageBorderProps` 为空时写旧式方框：页边起算、单实线、sz 4、space 24、自动色。
- 分页显示用 `pagination-gaps.ts` 中的 `pageBorderStyleOf` / `pageBorderLineCss` / `pageBorderArtStripStyle`；艺术型边框以 SVG 平铺绘制。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | 复用既有节级操作 `setSectionLayout {sectionId, expectedSectionSha256, values}`，`values` 新增 `pageBorder`（布尔）和 `pageBorderProps`（对象或 `null`）。末节经 saveDocx 的 `section`，非末节经固定引擎 `applySectionSettings` 写回；不改引擎。 |
| 预设 | `bridge/page-border-presets.json` 从固定源对话框逐项取出线型 24、宽度 9、艺术型 170；前端常量与之一致（单测比对）。 |
| 桥接校验 | `bridge/docx-page-borders.ts`，整批先验：<br>- 字段白名单，`pageBorderProps` 只在 `pageBorder:true` 时允许。<br>- 线型、艺术型、宽度、距离（0–31 整数）在范围内。<br>- 颜色为大写 6 位十六进制。<br>- 艺术边不带颜色、阴影或三维；阴影与三维互斥。<br>- `spacePt` / `widthPt` 等于各边最大值。<br>- 节摘要必须一致。<br>- 与 `insertSectionBreak` 同批时整批拒绝（`page_border_section_break_conflict`），因为插入分节会改变节下标。<br>失败时不产生输出文件。 |
| 写后回读 | 重新解析输出，节数必须不变，各目标节实际设置经归一化后（旧式方框展开成四边单实线 0.5pt / 24pt）与期望逐节比对，不符则 `page_border_write_not_applied`。 |
| 前端 | `docx-page-borders.ts`：模型与 props 互转（移植自固定源），校验与桥接一致。<br>`docx-page-border-dialog.ts`：纯 DOM 移植固定源对话框，沿用固定源 `.pb-*` 样式；应用于“整篇文档 / 本节 / 本节-仅首页 / 本节-除首页外所有页”（多节时标注第 n 节）。<br>功能区菜单为“方框 / 无 / 页面边框…”，触发按钮回显当前节状态。<br>修改记入原生事务历史，可撤销、重做；改回来源值即撤回该节修改，同节其他版式修改保留；刷新后从草稿恢复（恢复时逐项重验）。<br>分页预览显示待保存边框。 |
| 禁用原因 | 以下情况按钮禁用，并在提示中写明原因：<br>- 文档不可编辑。<br>- 草稿中已有插入分节。<br>- 草稿中已有水印（“页面边框与水印需分开保存”）。<br>- 目标节有待保存的分节变更。 |

## 证据

- **桥接测试** `reporting/doc_engine/bridge/tests/docx-page-borders.test.ts`（`node --test`：`# pass 3` / `# fail 0`）：
  - 预设数量。
  - 两节文档：第 1 节自定义双线 C00000、仅首页、仅上下边；第 2 节方框。XML 与 inspect 回读一致。
  - 全部节改为艺术型 apples，再清除。
  - 15 类非法值、摘要过期、与插入分节同批都被拒绝，且无输出文件。
- **Python 测试** `reporting/tests/test_docx_native_page_borders.py`（`5 passed in 13.19s`），经隔离的固定引擎：
  - 两节整篇阴影 3pt 1F4E79，ZIP 回读每节 `pgBorders` 属性与四边（`sz 24`、`shadow 1`）。
  - 段落与来源一致；变化部件 ⊆ {word/document.xml, docProps/core.xml}。
  - 第 2 节方框（页边起算、sz 4、space 24、auto）；清除后无边框。
  - 4 类参数化拒绝。
- **前端测试** `frontend/src/docx-page-borders.test.ts`（`Tests 5 passed (5)`）：
  - 预设与桥接 JSON 一致。
  - 模型与 props 往返。
  - 校验、草稿构建、撤回、保留同节边距。
  - 对话框交互。
  - 功能区菜单与禁用原因。
- **类型检查**：`tsc --noEmit` exit 0，无错误（需 `--max-old-space-size=8192`，默认堆会内存溢出）。
- **浏览器冒烟** `frontend/smoke/docx-page-borders-gui-smoke.mjs`（Chromium，开发服务器模式，真实 Python→Node 引擎；授权与修订路由为 fixture），exit 0，依次验证：
  1. 第 1 节设方框，撤销后草稿为空，重做后恢复。
  2. 选“无”撤回修改。
  3. 对话框选阴影、宽 3pt、#1F4E79、整篇文档，草稿中得到 2 条 `setSectionLayout`。
  4. 分页预览两页均绘出带阴影的深蓝边框（截图目视）。
  5. 刷新后草稿恢复。
  6. 保存为修订 2，下载 SHA 与保存一致。
  7. 独立 ZIP 回读：两节 `pgBorders` 均为 offsetFrom page，四边 `single / sz 24 / space 24 / 1F4E79 / shadow 1`；去掉 pgBorders 后 document.xml 与来源相同；页眉未动；变化部件只有 document.xml 与 core.xml。
  8. 重开修订 2，触发按钮呈激活状态，草稿为空。
- **渲染**：LibreOffice 把下载件转成 PDF，两页（两节）均显示右下带阴影的深蓝页面边框。
- **冒烟发现并已修复的问题**：脚本内 Python 正则在 JS 模板字符串中丢失反斜杠，导致“正文除边框外不变”的断言误判为假。实际文件无差异。
- **回归**：
  - Word 前端 `vitest run src/docx`：本次改动后 `Tests 6 failed | 1108 passed (1114)`。
  - 失败的 6 项在临时 worktree 中检出基线 `1e0b6e31` 复跑，得到同样 6 项：`docx-ribbon` 行距 1 项、`docx-text-revisions-main-collector` 4 项、`docx-body-decorations` 1 项。均为上游既有问题。

## 与固定源的差异

- 页面边框不能与插入分节或水印在同一次保存中提交，需分开保存；按钮会写明原因。
- 对话框为纯 DOM 移植。
- “应用于”四项与固定源一致；“仅首页 / 除首页外”经 `display` 写入并由桥接测试回读（firstPage），浏览器冒烟只走了“整篇文档”。
- 编辑区连续纸面不绘制边框，只在分页预览中显示，与固定源一致。
- 用对话框重新确认未改动的已解析边框时，可能把等价设置再写一次。`samePageBorder` 按 JSON 比较，不做语义归一。

## 未验收范围

- 生产构建（vite preview）、真实授权、发布链路。
- 在 Microsoft Word 中打开输出文件。
- 艺术型边框的浏览器端视觉验收：桥接已覆盖写入与回读，未截图验证。
