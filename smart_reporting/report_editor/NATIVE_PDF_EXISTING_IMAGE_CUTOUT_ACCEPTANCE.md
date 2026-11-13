# PDF 已有图像去除背景验收

2026-11-13。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 PDF Ribbon 已全部对齐。

## 固定源行为

- **算法**：`apps/pdf/src/renderer/cutout.ts` 的 `removeBackground(img, tolerance)`。
  - 沿图像四边采样，聚类出最多 4 种背景代表色。
  - 以“与任一代表色的距离不超过容差阈值”为可通行条件，从四边做 4 连通泛洪，把与边缘相连的背景像素 alpha 置 0。
  - 被主体包围、与边缘不相连的同色区域保留。
- **入口**：`App.tsx` 浮动工具条“去除背景”打开 `CutoutDialog`，容差 0–100，默认 `DEFAULT_CUTOUT_TOLERANCE = 30`，带实时预览画布。
  - 结果与翻转、透明度一样，经 `bakeSourcePng` → `transformPngPixels` → `commitBaked` 走 `replaceImage` 写回。
  - `ImageBakeOp` 共四种：`flip`、`opacity`、`crop`、`cutout`，其中没有旋转。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | 在 `transformExistingImage.bake` 上新增 `{kind: 'cutout', tolerance}`，容差为 0–100 的整数，没有新增操作种类。不能与替换图像或移动同批；范围必须等于原范围。 |
| 桥接 | `bridge/existing-image.ts` 先按 `BAKE_SCALE 3` 取图像自身的显示像素，再调用逐字节引入、未改动的 `removeBackground`，最后沿用上轮的写回与输出复核：其他图像逐像素不变、正文不变、页面框不变。固定源算法的背景采样与距离比较对通道顺序对称，可以直接处理 BGRA 像素。 |
| 前端 | 编辑 ▸ 编辑图像 ▸ 像素编辑新增“去除背景”和“去除背景容差”（默认 30）。越界时提示“0–100 的整数”。草稿支持撤销、重做和刷新恢复；保存前必须先核对实际 PDF 预览。 |
| 约束 | 与上轮一致：只对可替换、直接位于页面上、矩阵无旋转无镜像的图像开放。 |

## 证据

- **桥接测试** `reporting/pdf_engine/bridge/existing-image-cutout.test.ts`：
  - 白底红块图像去除背景后，四角与侧边 alpha 为 0，中心红色不透明；目标按 360×360 取样，范围不变；另一张图像与正文不变；同一输入的输出摘要可复现。
  - 越界、小数或缺失的容差、多余字段、同批移动、与替换同批均被拒绝。
- **PDF 引擎完整测试**：`# tests 299 # pass 299 # fail 0`。
- **Python 测试** `reporting/tests/test_native_pdf_existing_image_cutout.py`（4 项）：
  - 未确认预览时拒绝保存；确认后保存，下载字节与预览文件一致。
  - pypdf 回读：目标为 RGBA 360×360，四角 alpha 为 0，中心红色不透明；另一张图像保持 4×4；正文保留；来源文件不变。
  - 越界容差、缺失容差、同批移动均被拒绝。
- **前端单元测试** `frontend/src/pdf-existing-image-bake.test.ts`：新增 cutout 用例，两个文件共 19 项通过。
- **浏览器冒烟** `frontend/smoke/pdf-existing-image-cutout-smoke.mjs`：Chromium + 真实 Python→PDF 引擎链路，授权和修订路由用 fixture，开发服务器模式。
  - 流程：选“去除背景”，默认容差 30 → 填 101 被拒 → 改回 30 暂存 → 撤销 / 重做 → 刷新恢复 → 核对实际预览 → 保存为修订 2 → 下载字节与保存一致。
  - pypdf 回读：目标为 600×450，四角为 `[255,255,255,0]`，中心为 `[220,30,30,255]`；绿色图像不变；正文保留；来源文件不变。重开修订 2 正常。
  - pdftoppm 渲染：目标下方的黄色底块从原白色背景处透出，红色主体保留。

## 与固定源的差异 / 未验收

- 对话框没有固定源的实时预览画布，实际效果在“校验当前修改”的服务端预览中核对。
- 对已经带透明的图像重复去除背景时，已透明像素视为可通行，与固定源一致。
- 90° 旋转不在固定源 `ImageBakeOp` 中，未做。
- 生产构建、真实授权与发布链路未验收，也未在 Acrobat 中人工核对。
