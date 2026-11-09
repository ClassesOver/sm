# PDF 绘图工具验收

2026-11-09。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。单项功能闭环，不代表 PDF Ribbon 全功能对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` `DRAW_TOOLS`：ink、measure、rect、ellipse、arrow、polygon、caret、note；已接通 **ink / rect / ellipse / arrow / polygon / caret**（measure 仍待标定比例设计），按源顺序放在 Annotate ▸ Draw Tools。
- `DrawLayer.tsx` `DRAW_COLORS`：红 `[0.86,0.22,0.18]`（默认）、黄、绿、蓝、黑；绘图颜色独立于高亮颜色。
- `save-pdf.ts` `DrawingInput`：`rect`/`ellipse` 为 PDF user space 矩形，`arrow` 为 from/to，`ink` 为路径数组；`polygon` 为顶点数组（≥3）、`caret` 为插入点；引擎写成 Square/Circle/Line(带箭头)/Ink/Polygon/Caret 批注并生成外观流。未新增写入器。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `{kind:'addDrawing', pageId, shape, rect｜from+to｜paths｜vertices｜point, color, width}`，宽度 2pt |
| 多边形交互 | 逐点点击（相邻 <2pt 去重），双击或 Enter 完成，Esc 或切换工具取消；进行中以虚线预览 |
| 前端 | 绘图模式拖动生成；端点夹到当前可见范围；手绘采样 ≤2000 点；草稿以 SVG 叠加预览；颜色下拉沿用源五色；空白页/已删除页拒绝 |
| 桥接 | zod 严格字段 + 形状专属参数；坐标必须在（含同批裁切后的）可见范围内；宽度 0.25–24、颜色 0–1；输出摘要纳入预览确认 |

## 编辑链接（固定源 editLink / LinkDialog）

- Edit ▸ 图像、链接与水印 ▸ 编辑链接：拖出链接区域后弹出对话框，网址与页码二选一（输入一项清空另一项）；`www.` 自动补 `https://`。
- 与固定源的差异：固定源接受任意 scheme；本系统只接受 `http`、`https`、`mailto`，拒绝 `javascript:` 等。
- 页码按当前显示顺序输入，保存为来源页序号（引擎按删除/重排前页表解析），目标页在同一草稿被删除时前端与桥接均拒绝。

## 插入图像（固定源 ImageDialogs）

- Edit ▸ 插入图像：选择 PNG/JPEG（≤10MB），浏览器解码后按最长边 2000px 转为 PNG（编码 ≤6MB），在页面上拖出放置区域；草稿按页面矩阵精确预览（旋转页同样准确）。
- 桥接校验 PNG 签名、区域在页面内、非图像形状不得携带图像，交给固定引擎 `image` 绘图写成 Stamp 批注。编辑来源中已有图像仍未接入。

## 可视签名（固定源 SignatureDialog）

- Annotate ▸ Signature & Protection ▸ 签名：手写（签名板 480×160，最多 20 笔，矢量笔迹）或键入（固定源字体列表：手写体、行楷、楷体、宋体；按实测字形边界紧裁、透明背景栅格化）。上传图像签名复用“插入图像”。
- 放置：在页面上拖出区域；手写笔迹按签名板比例居中放入该屏幕区域，再经页面视口逆变换为 PDF 坐标并夹到可见范围，写为 Ink 批注（近黑色）；键入签名写为 Stamp 图像批注。
- 这是可视签名，不是证书数字签名；签名字段绑定（`formFieldName`）与已保存签名复用尚未接入。

## 水印与页眉页脚（固定源 StampDialog / stamps.ts）

- Edit ▸ 水印 打开与固定源相同字段的对话框：水印文字、角度 −90…90、不透明度 5–100%、字号 4–22% 页宽、颜色；页眉/页脚左中右、页码（默认开启）、起始页码；支持 `{page}` `{total}`。
- 位图由 `frontend/src/vendor/genoffice-pdf/renderer/stamps.ts`（与固定源逐字节一致，见同目录 `SOURCE.md`）的 `buildStamps` 按当前页序渲染；同尺寸页共享水印位图，矩形按 CropBox 原点平移。
- 草稿为 `setStamps{watermark, headerFooter, images, stamps}`；桥接校验 PNG 签名、总量 ≤12MB、位置在页面内、恰好覆盖全部保留页（含新空白页）、只能一次且不与页面尺寸同批，交给引擎 `stamps` 写入页面内容。
- 与固定源的差异：固定源在保存时按最终页序重新渲染；本系统的桥接在 Node 端无画布，因此设置后锁定重排、删页、插页、裁切、改尺寸（会提示原因），撤销或保存后再调整；重新设置会替换原设置。

## 证据

- `reporting/pdf_engine/bridge/drawings.test.ts`：真实引擎输出四种批注子类型、颜色、外观流和矩形范围；越界、错参、过短箭头、奇数路径、越界路径、非法颜色/宽度、外来页、空白页目标全部拒绝。
- `frontend/src/pdf-drawings.test.ts`：拖拽规范化、夹取、各类拒绝及删除页/空白页约束。
- 链接：`drawings.test.ts` 回读 URI 动作与目标页引用；拒绝 javascript:、双目标、无目标、越界页、已删除页、非链接形状携带链接字段。
- 水印：`bridge/stamps.test.ts`（真实输出每页图像 XObject 数、新空白页覆盖；拒绝缺页、越界、非 PNG、坏索引、空配置、越界角度、重复、已删页、与页面尺寸同批）；`frontend/src/pdf-stamps.test.ts`（页序、去重、CropBox 平移、结构锁定、覆盖校验）。
- `frontend/smoke/pdf-draw-smoke.mjs`（Chromium + 真实 Python→PDF 引擎，授权/修订路由为 fixture）：四种拖动工具 + 多边形逐点/双击 + 插入符号单击，切换蓝色 → 编辑链接（拒绝 javascript:、www. 补全、页码链接）→ 8 个草稿 SVG → 上传 PNG 并拖放插入图像 → 手写签名与键入签名“张三 Zhang”放置 → 设置水印“机密 Confidential”+ 页码并验证删页被拒绝 → 撤销/重做 → 刷新恢复 → 保存修订 2 → 下载字节一致 → pypdf 独立回读 Square/Circle/Line/Ink/Polygon/Caret 与逐项颜色，第 1 页含 2 个 Stamp（图像、键入签名）与签名 Ink 批注，每页均含水印与页脚图像，表单控件和第 2 页便签保留；pdftoppm 独立栅格化确认倾斜中文水印与“1 / 4”页脚可见，来源摘要不变。

注：本次排查发现 `pdf_engine/dist/cli.mjs`（打包测试生成、git 忽略）存在时生产优先使用打包产物；修改桥接后必须重新打包或删除该产物，否则会运行旧 schema。镜像构建会重新打包。
