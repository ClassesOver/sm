# PDF 已有图像裁剪 / 翻转 / 透明度验收

2026-11-12。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 PDF 已全部对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` 的图像浮动工具条提供水平/垂直翻转、裁剪、透明度。这三项都是“烘焙”：
  1. `bakeSourcePng` 用 `pageImagePng` 以 `BAKE_SCALE = 3` 取图像的显示像素；
  2. 在画布上执行 `flipPixels` / `multiplyAlpha` / `cropImagePng`；
  3. 作为 `replaceImage` 写回。裁剪时占位矩形按 `cropRect(原范围, 保留比例)` 缩小。
- `apps/pdf/src/main/image-edit.ts` 的 `renderImagePng` 用 PDFium `FPDFImageObj_GetRenderedBitmap` 只渲染该图像对象，不含其上的文字；长边上限 2400px。
- `apps/pdf/src/renderer/image-bake.ts` 是纯函数（`flipPixels`、`multiplyAlpha`、`cropRect`）。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 固定源文件 | `image-bake.ts` 与 `cutout.ts`（只用其中的 `PixelImage` 类型）逐字节带入。PDF 引擎侧放在 `reporting/pdf_engine/src/renderer/`，前端放在 `frontend/src/vendor/genoffice-pdf/renderer/`，哈希已登记。 |
| 操作 | 在现有的 `transformExistingImage` 上增加可选字段 `bake`：`{kind:'flip', axis:'h'|'v'}` / `{kind:'opacity', alpha}` / `{kind:'crop', crop:{l,t,r,b}}`。`bake` 与替换图像字段 `image` 互斥；不新增操作种类。 |
| 引擎适配 | `renderExistingImageBgra` 移植 `renderImagePng`：只在内存副本上放大，直接返回 BGRA（不经 Electron `nativeImage`）。`applyExistingImageReplaceBgra` 复用替换图像的写入器。 |
| 桥接 | 以 `BAKE_SCALE = 3` 取像素，调用固定源函数烘焙。裁剪的取整方式与 `cropImagePng` 一致。写回后复核以下各项，任一不一致即按现有规则保留实际产物并给出原因：<br>• 目标的新像素尺寸与范围<br>• 其他图像逐像素不变<br>• 正文<br>• 页面结构 |
| 限制 | 只允许“可替换”的图像，且图像直属页面、矩阵为正向、无旋转、无镜像（`axisAligned`）。原因：写回保留原矩阵，带旋转或镜像的图像会被变换两次，所以明确拒绝并给出原因。烘焙不能与移动同批：翻转和透明度的范围必须等于原范围，裁剪的范围必须等于 `cropRect`。 |
| 前端 | 在“编辑 ▸ 编辑图像”对话框里新增“像素编辑”：无 / 水平翻转 / 垂直翻转 / 裁剪（四边各裁去 0–99%）/ 透明度（1–100%）。选中后锁定坐标、禁用替换。草稿可撤销、重做、刷新后恢复；保存前须核对实际 PDF 预览。 |

## 证据

- `reporting/pdf_engine/bridge/existing-image-bake.test.ts`（3/3 通过，真实 PDFium 输出）：
  - 8×8 四色象限图做水平、垂直翻转后，各象限颜色按预期互换；以 3 倍取样得到 300×240 像素；范围、另一张图像和正文都不变。
  - 裁剪保留左上 1/4，得到 150×120 像素，范围等于 `cropRect`。
  - 透明度 50% 时 alpha 约为 128。
  - 同一操作的输出摘要可复现。
  - 以下情况均被拒绝：旋转图像、共享像素流、同时移动、非法方向或比例、整数百分比以外的值、`image` 与 `bake` 同时出现。
- `reporting/tests/test_native_pdf_existing_image_bake.py`（3/3 通过）：翻转、裁剪分别经过“未确认被拒绝 → 预览确认 → 保存 → 下载与预览文件逐字节一致 → pypdf 回读像素与尺寸 → 预览摘要可复现 → 来源修订不变”；同时移动被拒绝。
- `frontend/src/pdf-existing-image-bake.test.ts`：翻转、透明度原位暂存，裁剪范围等于固定源 `cropRect`，拒绝情况与桥接一致。与原有的 `pdf-existing-image.test.ts` 合计 18/18 通过。
- `frontend/smoke/pdf-existing-image-bake-smoke.mjs`（Chromium、开发服务器，真实桥接链路；授权和修订路由用 fixture），输出 `"ok":true`：
  - 裁剪：裁去右侧 50%，暂存范围正确；像素编辑与替换按钮互斥。随后撤销。
  - 透明度填 0% 被拒绝。
  - 水平翻转：撤销 → 重做 → 刷新后恢复 → 实际预览确认 → 保存为修订 2 → 下载字节与保存一致。
  - pypdf 回读：目标为 600×450 像素且左右颜色互换，绿色图像与正文不变，来源文件不变。
  - 范围保持不变；修订 2 可以重新打开；pdftoppm 渲染为左蓝右红。

## 与固定源的差异 / 未完成

- 固定源在页面上选中图像后从浮动工具条操作，裁剪用拖拽对话框；这里在“编辑已有图像”对话框里按百分比输入。
- 固定源对带旋转或镜像的图像不加限制；这里明确拒绝，避免方向被重复变换。
- 透明度会叠加：对已经烘焙过透明度的图像再设一次，会在原 alpha 上相乘。固定源跨保存也是这样；固定源在同一会话内用 `opacityBase` 避免叠加，原生每次修改都单独保存，不涉及这一点。
- 去除背景（`cutout`）、旋转 90° 未接通。
- 未验收：生产构建、真实授权和发布链路；未在 Acrobat 中人工核对。
