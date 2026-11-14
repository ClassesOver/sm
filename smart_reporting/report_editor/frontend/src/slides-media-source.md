# PPTX 音视频组件族来源与边界

固定源：`/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。运行时分类、尺寸、codec 解析和引擎 writer 与固定源逐字节一致；原断言测试只改 import 路径。许可证沿用 GenOffice Apache-2.0。

| 源能力 | 浏览器宿主接线 |
| --- | --- |
| `RibbonInsertTab.onInsertMedia` → `insertMediaFile` | 音频/视频 FilePicker；只读字节，不开放本机路径 |
| `insertDroppedMedia` → `slides:add-media-bytes` | 画布拖入源支持容器；MIME 不稳定时按固定源扩展名分类；drop 中心转为 EMU |
| `shared/media-kinds.ts` | `bridge/source-media/media-kinds.ts`，五视频/五音频容器 |
| `main/video-size.ts`、`mp4-audio-sniff.ts` | 同名 source-media 文件；原尺寸、居中、不放大规则与 AVI/不支持音轨告警 |
| `embedMedia` → `addMedia` | `bridge/pptx-media.ts` 直接调用现有 `packages/pptx-engine/src/media-insert.ts`；真实 media part、poster、legacy + p14 双关系 |
| `slides:media-data` | 已授权 render-tree 对同一实际 PPTX 快照读取媒体 bytes、SHA256、size、dataURL；外链不自动加载，缺失媒体明确返回原因 |
| `App.startMediaPlayback` 与编辑 DOM 播放层 | 双击媒体或当前页播放入口；`slides-media-playback.ts` 原生 controls、真实错误提示、关闭/切页/保存/销毁清理 |
| `ShowMediaLayer` | `vendor/genoffice/renderer/ShowMediaLayer.tsx`；IPC 改为受控 props，保留源 epoch/mediaBase 顺序语义；play rejection、error、ended 与清理显式处理 |
| `animation-play` 的 `mediaPlay/mediaPause/mediaStop` | 既有分步动画播放器；实际源对象身份、播放从零/暂停切换/停止回零；编辑动画预览静音跳过媒体，放映执行 |
| `toggleScreenRecord` | 明确未验收且入口禁用；未实现系统捕获，不宣称覆盖屏幕录制 |
| 系统缩略图 `videoPoster(path)` | 浏览器不接本机路径/系统缩略图，沿用 source writer 的默认 poster，不冒称提取首帧 |
| 替换媒体 | 固定源没有独立 replaceMedia 动作；普通图片替换入口不替换音视频文件，不将更换海报冒称替换媒体 |

`mediaInsertions` 复用现有 NativeDraft、Undo/Redo、修订/保存与授权预览链。单项最多 6 MiB，媒体与已有图片上传总量最多 8 MiB；仍受 NativeDraft 12 MiB JSON 上限限制。先整批校验再改草稿。取消/销毁通过 AbortSignal 清理 FilePicker/FileReader，迟到结果还必须匹配来源 SHA、页、草稿与保存状态。

新插入媒体从实际写出的预览 PPTX 显示/播放，可撤销此项、Undo/Redo、刷新恢复。保存后独立 ZIP、python-pptx、实际媒体 bytes 再回读；不覆盖来源文件。不触及报告发布门禁或下载签发链。

容器可嵌入不等于浏览器可解码。AVI 与不支持音轨提前提示；其他实际播放错误明确显示失败并保留原始字节。屏幕录制、3D、演讲者视图、自动换页与文字内链接不在本批验收范围。媒体相关代码未新增 Plotly 或交互图协议。

验收 runner：`smoke/pptx-media-source-smoke.mjs`（source 或统一冻结 native），`pptx-media-native-fixture.mjs`（显式夹具授权/修订，真实 writer/reader/下载），`pptx-media-source-fixture.py`（生成与独立回读），`build-pptx-media-engine.mjs`（显式 workspace aliases 的隔离引擎，不写共享 dist）。夹具授权不可当作生产授权、正式持久化服务或真实系统录屏验收。

2026-11-13 环境重启丢失最初内存盘 before 与 RED 日志；恢复后证据位于 `/home/junge/codex-evidence/smart_reporting/office-media-20261113-recovery`。`recovery-baseline` 仅为恢复中途快照，不能伪称实施前基线。最终四视口冻结结果由统一 freeze 单独记录。
