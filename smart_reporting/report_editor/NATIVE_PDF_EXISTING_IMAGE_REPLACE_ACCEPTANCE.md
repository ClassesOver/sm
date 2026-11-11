# PDF 已有图像像素替换验收

2026-11-11。固定来源提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次只验收这一项功能闭环，不代表 PDF Ribbon 已全部对齐。

## 固定源行为

- `apps/pdf/src/renderer/App.tsx` `replaceExisting`：对来源 PDF 中已有的图像排队一条 `replaceImage`，携带 `oldRect`（定位）、`rect`（最终范围）和新图像 PNG；足迹与层级保留。
- `apps/pdf/src/main/image-edit.ts` `replaceImage`：按 `oldRect` 找到图像对象，用 `FPDFBitmap_CreateEx` + `FPDFImageObj_SetBitmap` 替换像素（传入所在页面以清除旧缓存），矩阵不变，随后走同一几何变换。解码用 Electron `nativeImage`。

## 原生实现

| 层 | 内容 |
| --- | --- |
| 操作 | 沿用已有的 `transformExistingImage`，新增可选字段 `image`（PNG base64，≤6MB 编码）。固定源 `replaceImage` 同样是 oldRect + rect + image，因此不新增操作种类；预览确认、单独保存、Python 合同与草稿恢复路径都不变。 |
| 引擎移植 | `bridge/existing-image-engine.ts` 移植固定源 `replaceImage`；Electron 解码换成 pdf-lib 自带的 PNG 解码器（直出非预乘 alpha），只接受 PNG，上限 4096×4096 像素。 |
| 桥接 | 写入前先解码校验替换图；来源身份（imageId + 图像指纹 + 来源摘要）不符、目标不可编辑或越界即整批拒绝。写入后复核：目标位置出现新像素尺寸的图像，其余图像逐像素不变，正文与页面结构不变；复核失败保留实际产物并标为未执行（不阻断签发）。 |
| 共享图像流 | `SetBitmap` 改写的是图像流本身：同一像素数据被其他位置（含其他页）引用时，替换会连带改变那些位置。检出后该图像标为 `replaceable:false` 并说明原因，前端禁用“替换为新图像…”，桥接拒绝。仍可移动/缩放。 |
| 前端 | 编辑 ▸ 编辑图像对话框新增“替换为新图像…”：选择 PNG/JPEG（≤10MB），浏览器按最长边 ≤2000px 转 PNG；可同时修改 X/Y/宽/高；“不替换”撤回所选文件。暂存后可撤销/重做，保存前须核对实际 PDF 预览并勾选确认。 |

## 与固定源的差异

- 固定源的裁剪、翻转、透明度、抠图都是在画布上处理像素后走同一 `replaceImage`；本次只接通“用新文件替换”，**像素裁剪等其他像素编辑未接通**。
- 固定源可在页面上直接点选图像；这里沿用已有对话框按页列出可编辑图像。
- 固定源不检查共享图像流；这里拒绝替换共享流，避免静默改动其他位置。

## 证据

- `reporting/pdf_engine/bridge/existing-image-replace.test.ts`（真实引擎）：
  - PNG 解码为 BGRA，非 PNG 与非法 base64 拒绝。
  - 0° 与 90° 页上替换：目标变为 3×2 新像素、足迹不变，另两张图逐像素不变，正文与页面结构不变，来源字节不变。
  - 替换同时移动/缩放；预览确认摘要随图像字节变化。
  - 拒绝不可解码图像、过期身份、多余字段、越界范围；共享图像流 `replaceable:false` 且写入前拒绝；重叠图像不可编辑。
- `pdf_engine` 全部桥接测试 283/283 通过。
- `reporting/tests/test_native_pdf_existing_image_replace.py`（真实服务）：未确认保存被拒；预览、`preview.pdf` 与保存的下载字节一致；pypdf 回读目标为 12×9、另一张 4×4 不变、正文保留；来源修订不变。共享流来源的 `replaceable` 为 false 且预览被拒。
- `frontend/src/pdf-existing-image.test.ts`：替换操作构造、只对可替换目标生效、非法 PNG/超限/非字符串被拒。
- `frontend/smoke/pdf-existing-image-replace-smoke.mjs`（Chromium + 真实 Python→PDF 引擎链路，授权/修订路由为 fixture）：
  1. 打开编辑图像对话框，选中左侧图像，GIF 文件被拒。
  2. 选择 40×30 PNG，暂存的操作携带 `image`，范围等于原足迹。
  3. 撤销、重做。
  4. 校验当前修改 → 实际预览 → 勾选确认 → 保存修订 2，下载字节与保存一致。
  5. pypdf 独立回读：目标为 40×30、左上角像素为替换图的蓝色；另一张绿色 2×2 不变；正文保留；来源摘要不变。
  6. 重开修订 2；渲染图中左侧为新图像（蓝底黄块），右侧绿色不变。

本次在开发服务器模式运行（`PDF_IMAGE_REPLACE_SMOKE_PRODUCTION=0`）；生产镜像、真实授权与发布链路未在此验收。
