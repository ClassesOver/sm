# 图片裁切覆盖层来源

CropOverlay.tsx 和 esc-overlay.ts 原样复制自 GenOffice commit `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `apps/slides/src/renderer/`，遵循上游 Apache-2.0 许可；哈希见 SOURCE-CROP-SHA256.json。

本地缩放与生命周期适配位于 `../../slides-native-crop.tsx`。裁切与框作为一次 NativeDraft 修改提交；宿主整批校验，子进程只返回最终保存的完整 PPTX，不暴露半完成产物。图片写入复用 editPictureSrcRect 和 updateConnectorsForMoved，不新增 OOXML writer 或 Markdown raw loader。
