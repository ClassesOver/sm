# PDF 合并页面 / 拆分页面验收

2026-11-10。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 PDF Ribbon 已全部对齐。

## 固定源行为

- **合并页面**：`App.tsx` 中 `MergePagesDialog` 的每张页数为 2–16，默认 2；顺序分纵向（默认）和横向；可选分隔线。由 `save-pdf.ts` 的 `mergePagesBytes` 写出新文件，纸张尺寸取第 1 页；2 合 1 时纸张改为横向。
- **拆分页面**：`SplitPagesDialog` 提供 2 / 4 / 9 三档。由 `splitPagesBytes` 按显示方向把每页均分成多页，每份是副本，只收紧 MediaBox/CropBox，内容不丢失。
- 固定源两项都写出新文件；原生适配的 N 合 1 先展平可见批注/表单外观，交互、书签和附件不保留。含表单的拆分页当前拒绝，避免丢失字段。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | `{kind:'mergePages', perSheet, direction, separator}`、`{kind:'splitPages', perPage}`，都必须单独保存 |
| 前端 | 页面 ▸ 合并与拆分。草稿里已有其他修改时按钮禁用，并说明原因。确认后立即请求服务端实际预览，预览期间页面列表采用输出模型，页签显示“重排版预览”。点“返回原稿编辑”后可以撤销。 |
| 桥接 | zod 严格校验。含签名字段的来源会被拒绝。调用的是固定引擎未改动的写出函数，随后回读并核对页数（合并为 ⌈n/N⌉，拆分为 n×N）。固定源会写入当前时间，这里改为沿用来源的 CreationDate/ModDate（来源没有就删除），这样同一草稿每次输出逐字节一致，预览确认摘要才能复现。 |
| 服务端 | PDF 预览统一走回执路径，每种修改都返回绑定实际输出的 `previewDigest`。此前绘图、图章、空白页预览不返回摘要，前端在“校验当前修改”时会报错，这次一并修复。 |

## 证据

- `reporting/pdf_engine/bridge/page-layout.test.ts`：
  - 5 页合并为 4 合 1 得 2 页；2 合 1 得 3 页且为横向。
  - 拆为 4 后得 20 页，每页 150×200。
  - 间隔 1 秒重复执行，输出摘要不变。
  - 与其他修改同批、参数非法、来源摘要不符时均被拒绝。
- `reporting/tests/test_native_pdf_layout_service.py`：
  - 绘图、涂黑、拆分页面三类预览都返回摘要，且 `preview.pdf` 的摘要与之一致。
  - 合并页面保存后，下载文件的页数与预览一致。
- `frontend/src/pdf-page-layout.test.ts`、`pdf-page-ribbon.test.ts`。
- `frontend/smoke/pdf-layout-smoke.mjs`：在 Chromium 中跑真实的 Python→PDF 引擎链路，预览与预览文件也走真实桥接；授权和修订路由用 fixture。步骤：
  1. 有其他修改时按钮禁用。
  2. 拆为 2 后实际预览为 10 页。
  3. 返回原稿并撤销。
  4. 合并页数填 17，提示超出范围。
  5. 改为 4 合 1、横向、加分隔线，预览为 2 页，页签显示“重排版预览”。
  6. 保存为修订 2，下载字节与保存一致。
  7. 用 pypdf 独立回读：第 1 张含第 1–4 页文字，第 2 张含第 5 页文字；来源文件不变。
  8. 重新打开修订 2，仍为 2 页；渲染图中四格与分隔线位置正确。

本次在开发服务器模式下运行（`PDF_LAYOUT_SMOKE_PRODUCTION=0`）。生产镜像、真实授权和发布链路没有在本次验收范围内。


## 审查修复

N 合 1 的测量/绘图/表单外观改为静态内容；无可确认外观则拒绝。含 AcroForm 字段的拆分页在前后端禁用，XFA 两种排版均拒绝。独立回读与引用证明见 `NATIVE_PR210_PRESERVATION_ACCEPTANCE.md`；此处未宣称保留表单交互。

N 合 1 输入现在按可见 CropBox 归零并换算物理 UserUnit，保留 /Rotate；修正固定 embedder 默认零原点 MediaBox 的偏差。裁切外内容仍不属于安全删除，底层源内容可保留。NeedAppearances 请求重新生成的未确认表单外观拒绝展平，避免把过期外观当成最新值。
