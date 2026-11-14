# PPTX 音视频组件族专项验收（2026-11-13）

本批完成固定源音视频插入、读取、编辑播放、放映播放及媒体分步动作组件族接线；最终统一冻结矩阵 **4/4 通过，错误 0**。屏幕录制入口禁用且未验收，3D 不属于本批。浏览器不能解码的媒体明确返回失败原因，不能将成功嵌入等同于成功播放。

## 来源与实现

- 权威源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`，沿用 Apache-2.0 许可证。
- 分类、尺寸、MP4 音轨解析 helpers 及 `media-insert.ts` writer 与固定源逐字节一致；原 helper 测试仅调整 import。
- Audio/Video FilePicker 与画布拖入读取实际字节，复用源 `addMedia` writer；生成实际 media part、poster、legacy/p14 双关系。授权 render-tree 从同一实际 PPTX 快照读取媒体 bytes、SHA256、大小及 dataURL；不开放本机路径，外链不自动加载。
- 编辑 DOM 播放和源 `ShowMediaLayer` 使用实际 HTML5 audio/video；保留源 epoch/mediaBase 顺序，处理真实 play rejection/error、暂停、停止和销毁清理。`mediaPlay/mediaPause/mediaStop` 使用真实对象身份、零时长。
- 插入复用 NativeDraft、Undo/Redo、待修改移除、刷新恢复及修订保存下载；取消、切页、保存、销毁与迟到 FileReader 结果均有保护。单媒体 6 MiB，与图片类上传共用 8 MiB 总量。
- 普通图片替换不能替换音视频；源没有独立 replaceMedia API。系统海报提取、录屏、3D、演讲者视图、自动换页不在本批范围。
- 完整源映射和限制见 `frontend/src/slides-media-source.md`。本批没有新增 Plotly 或修改报告发布门禁/下载签发链。

## v4 完整矩阵冻结身份

证据根目录：`/home/junge/codex-evidence/smart_reporting/office-media-20261113-recovery`。

- 统一物理前端/engine 源：`/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113/source`。
- 静态目录：上述 source 下的 `smart_reporting/report_editor/static`。
- `.vite/manifest.json` SHA256：`96be3d8e01bc69c68f42693a20f81712ff47614e94e9194a4c9856ba4b8d5b94`。
- root 统一 v4 构建、tsc、原预算检查通过；本专项未重复完整构建/测试。统一结果保存在 `office-styles-media-format-fill-20261113/build-v4.log`、`budget-v4.log`、`frozen-build-identity.json`。
- 既有隔离媒体 engine 的 **129 个非 npm 输入**与统一物理 snapshot SHA 精确相等，150 个 npm 输入明确不在该源码比对范围；两份 bundle 身份一致。回执 `engine-frozen-snapshot-equivalence.json`。
- snapshot 未包含 Python 后端或 `.venv`，稳定 runner 从原工作区调用实际后端、加载上述冻结 static；`native_office.py`、`pptx_media.py`、`slides.py` 及三份 runner/helper 起止 SHA 相同，见 `frozen-before-identities.json`、`frozen-after-identities.json`。

## 一次四视口真实浏览器矩阵

使用全新 `frozen-fixture`，只复制六份源/插入输入，不复用旧修订输出。`pptx-media-source-smoke.mjs` 默认冻结模式运行一次，退出码 0，日志 `frozen-native.log`，结果 `frozen-native/evidence.json`。

| 视口 | 编辑视频时间推进（秒） | 原音频时间（秒） | 放映动作与失败提示 |
| --- | --- | --- | --- |
| 1440×900 | 0.298550 → 0.743006 | 0.322491 | Play/Pause/Stop、AVI 明确失败均通过 |
| 320×640 | 0.312112 → 0.755543 | 0.311282 | 同上 |
| 640×360 | 0.296435 → 0.745443 | 0.318156 | 同上 |
| 390×320 | 0.301195 → 0.744794 | 0.315958 | 同上 |

每视口原视频 `readyState=4`、`videoWidth=320`，两实际视频帧 SHA 不同；音频真实播放，放映真实暂停及停止回零，播放未改变草稿。截图 `frozen-native/editor-*.png`、`show-*.png`；已视觉查看四种编辑视口及最小视口放映，播放器位于视口内。

最终浏览器实际获取的 **157 个 JS/CSS 资源**均逐项与冻结文件 SHA 相等，manifest 校验通过。回执 `frozen-http-identity-verification.json`；matrix evidence SHA256 为 `1db90710e18738e1a9e4f844446c5bb5c74400f84341d0346adc013f62f1e638`。

## 插入、保存下载与独立回读

最终矩阵执行音频 FilePicker、视频拖入、新媒体实际预览播放、Undo/Redo、待修改移除/撤销、刷新恢复；真实保存修订一次，真实 HTTP 下载一次。保存后按钮禁用。

- 原 PPTX SHA256（起止不变）：`5fe02aa0d15177f5662523e64bede9c0cb01e83eb4135bb45a0cb550e69b0dc9`。
- 本次下载/修订 PPTX：1,123,765 字节，SHA256 `0429647528dd97460df90c91ef2bfc07f73c453db7d302b5eadb876072940bbf`。
- 新音频 `ppt/media/media7.wav`：288,078 字节，SHA256 `01bc9ba1e00abb20a1e6f5c9659e3e6ef68d87bdea95dd3baef538ccecab42ed`。
- 新视频 `ppt/media/media9.webm`：126,019 字节，SHA256 `c0e4f0c10a0111063a366165e4d79c2869e5d95a4553f467760f39304453b62c`。

独立 ZIP 与 python-pptx 回读验证：两新增媒体逐字节等于插入输入，每项均有 legacy/p14 双关系；正文、讲稿及其他原部件保留。只改 slide1.xml 及其 rels，新增两 media 和两 poster，共四个 part；所有 XML 可解析，ZIP 完整性通过。详细结果在 `frozen-native/evidence.json.saved`。

额外只做一次修订重开：将本次已下载字节作为 revision 2、parentRevision 1 的显式 native 夹具输入，重新经实际 inspector/render-tree 打开；四媒体存在，新音频播放至 0.318120 秒，新视频至 0.279797 秒、宽 240，均 `readyState=4` 且 `paused=false`。重开来源 SHA 与下载身份相同，错误 0。证据及独立夹具为 `reopen-revision/evidence.json`、`reopen-revision/reopen.mjs`、`revision-2-native-fixture.mjs`，截图 `reopened-revision-2.png`。

## 既有定向验证与证据边界

恢复后已去重的定向验证共 **116 例**：Python 16、源 helper/bridge 28、前端 72，见 `test-summary.json` 及其日志。新 screenRecording 图标唯一失败修正后仅重跑失败用例；未重复完整测试。source native 单视口此前也完成真实播放保存下载，证据 `source-native/evidence.json`，不能替代本次冻结矩阵。

授权和修订宿主是明确标识的 native fixture；实际 writer、reader、HTTP 静态资源、浏览器播放及下载字节均真实。该结果不能冒称生产授权系统、正式持久化服务或系统录屏验收。

环境重启曾丢失最初内存盘 before/RED 日志，已在 `recovery.md` 记录；`recovery-baseline` 是中途快照，`recovery-continuation.patch` 仅恢复后差异，不能冒称实施前 baseline 或完整 task-only patch。未将并发工作区完整 git diff 当作本任务补丁。

## v5 最终产物续验（同一下载，零保存）

root 在 v4 后仅修复 PDF 低高度问题，媒体源码未变。v5 独立 source 的 build（46.32 秒）、tsc、原预算均通过；媒体不重复完整矩阵、插入、保存或下载，保留上述 v4 完整行为证据。

- v5 static：`/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113/source-v5/smart_reporting/report_editor/static`。
- v5 manifest SHA256：`11c248ae3a4c6fa31fad99f04d2e72437abc4440569e1d846615616b7f442e17`。
- 续验实际读取同一 v4 已下载 PPTX，SHA256 仍为 `0429647528dd97460df90c91ef2bfc07f73c453db7d302b5eadb876072940bbf`，以 revision 2、parentRevision 1 的显式 native fixture 重开。
- 四媒体均被实际 inspector/render-tree 读出；新增音频播放至 **0.317840 秒**，新增视频至 **0.283621 秒**、宽 240，均 `readyState=4`、`paused=false`，错误 0。
- 浏览器 **151 个实际 HTTP JS/CSS 资源**逐项等于 v5 冻结文件 SHA，manifest 校验通过。明确计数 `saveCount=0`、`downloadCount=0`，请求中没有 save；没有重跑 v4 完整矩阵。
- 现有 engine 的 129 个非 npm 输入与 source-v5 物理快照逐项等价；后端及原稳定 runner 六文件起止 SHA 不变。
- 证据 `reopen-revision-v5/evidence.json`，SHA256 `ab84e5ec6a15369c06ad31857bd591407b44d312dbe19ef9e6ce53d89c6e705f`；汇总 `reopen-revision-v5/verification.json`，等价回执 `engine-equivalence.json`，起止 `before-identities.json`、`after-identities.json`。独立续验运行器和 fixture 同目录保存，进程退出码 0；`reopened-revision-2.png` 已视觉查看，修订 2 和四媒体均显示正常。

因此最终证据分层为：**v4 四视口完整行为与保存下载回读 + v5 最终静态资源身份、同一真实下载零保存重开和真实音视频播放**。v5 续验仍为显式夹具宿主，不提升为生产授权/正式修订服务验收。
