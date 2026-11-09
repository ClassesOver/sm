# PDF 绘图工具验收

2026-11-09。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。单项功能闭环，不代表 PDF Ribbon 全功能对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` `DRAW_TOOLS`：ink、measure、rect、ellipse、arrow、polygon、caret、note；本次接通 **ink / rect / ellipse / arrow**，按源顺序放在 Annotate ▸ Draw Tools。
- `DrawLayer.tsx` `DRAW_COLORS`：红 `[0.86,0.22,0.18]`（默认）、黄、绿、蓝、黑；绘图颜色独立于高亮颜色。
- `save-pdf.ts` `DrawingInput`：`rect`/`ellipse` 为 PDF user space 矩形，`arrow` 为 from/to，`ink` 为路径数组；引擎写成 Square/Circle/Line(带箭头)/Ink 批注并生成外观流。未新增写入器。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `{kind:'addDrawing', pageId, shape, rect｜from+to｜paths, color, width}`，宽度 2pt |
| 前端 | 绘图模式拖动生成；端点夹到当前可见范围；手绘采样 ≤2000 点；草稿以 SVG 叠加预览；颜色下拉沿用源五色；空白页/已删除页拒绝 |
| 桥接 | zod 严格字段 + 形状专属参数；坐标必须在（含同批裁切后的）可见范围内；宽度 0.25–24、颜色 0–1；输出摘要纳入预览确认 |

## 证据

- `reporting/pdf_engine/bridge/drawings.test.ts`：真实引擎输出四种批注子类型、颜色、外观流和矩形范围；越界、错参、过短箭头、奇数路径、越界路径、非法颜色/宽度、外来页、空白页目标全部拒绝。
- `frontend/src/pdf-drawings.test.ts`：拖拽规范化、夹取、各类拒绝及删除页/空白页约束。
- `frontend/smoke/pdf-draw-smoke.mjs`（Chromium + 真实 Python→PDF 引擎，授权/修订路由为 fixture）：四种工具拖动绘制并切换蓝色 → 4 个草稿 SVG → 撤销/重做 → 刷新恢复 → 保存修订 2 → 下载字节一致 → pypdf 独立回读 Square/Circle/Line/Ink 与逐项颜色，表单控件和第 2 页便签保留，来源摘要不变。

注：本次排查发现 `pdf_engine/dist/cli.mjs`（打包测试生成、git 忽略）存在时生产优先使用打包产物；修改桥接后必须重新打包或删除该产物，否则会运行旧 schema。镜像构建会重新打包。
