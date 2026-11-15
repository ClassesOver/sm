# Word 跟踪修订设置验收

日期：2026-11-13。本记录只覆盖 Word 顶层 `w:trackRevisions` 设置的浏览器保存闭环，以及对应的 bridge/host 回读；不把正文复杂修订、已有修订编辑、生产 HTTP 鉴权或桌面 Word 等价性扩大为已完成。

## 实现范围

- `frontend/src/docx-track-revisions.ts` 以来源 `sourceSha256` 绑定 `setTrackRevisions` 操作，保持启用状态不变时不产生操作，并拒绝过期来源、非法值和重复设置。
- `frontend/src/docx-main.tsx` 的 operation collector 保留 `nativeOperations` 中的 `setTrackRevisions`；此前冻结探针发现 collector 漏带该设置操作，已修复后重新构建验收。
- `reporting/doc_engine/dist/edit-docx.mjs` 仅在文档设置作用域处理该 operation；受保护或来源身份不匹配时拒绝使用设置数据。
- Python host/bridge 只改 `word/settings.xml` 的 `w:trackRevisions`。验收夹具另保留 `customXml/track-settings-keep.xml`，用于确认非目标部件未被重写。

## 冻结浏览器证据

隔离脚本：`frontend/smoke/docx-track-revisions-settings-built-smoke.mjs`。冻结静态目录为 `/tmp/docx-track-revisions-static-20261113`，真实 Chromium 版本 `157.0.8103.38`；完整输出为 `/tmp/docx-track-revisions-browser-20261113-verified5.log`，结构化结果为 `/tmp/docx-track-revisions-browser-20261113-verified5/result.json`，结果 `ok=true` 且 `errors=[]`。

实际链路为：来源修订 1（关闭）→ Review 开启 → 保存并下载修订 2（开启）→ 修订 2 重开读取开启 → Review 关闭 → 保存并下载修订 3（关闭）→ 修订 3 重开读取关闭。每次保存都校验 payload 只有一个来源绑定的 `setTrackRevisions` operation；下载响应再次读取并由 Python `inspect_docx`/ZIP/lxml 独立回读。

两次保存的产物身份如下：

| 修订 | 设置值 | 下载 SHA256 | 变化部件 |
| --- | --- | --- | --- |
| 2 | `true` | `b3eafc01282f0e534a09caa54658a775a52e3a7bb1586608cf12ef918f9e0d33` | `docProps/core.xml`、`word/settings.xml` |
| 3 | `false` | `d08f9ce0973e6c590f03dffb7aa2a5c1888e11275eed7e623026364b5fb09de3` | `docProps/core.xml`、`word/settings.xml` |

`docProps/core.xml` 是正常保存时的更新时间变化；自定义部件内容保持不变。冻结 manifest SHA256 为 `93161a5cad745a0bfc2fbb19b37407b480f2bc606b1e605d26aa39d4f439d119`；实际加载的 Word 主 chunk `lazy-docx-main-CJvBtME-.js` SHA256 为 `33691482c9d4637852211134ef3bf3b8b3cafc03ac925e774da073fc3edcc272`，engine chunk `lazy-native-docx-engine-NU3FOzrM.js` SHA256 为 `f4532289b84cc95a6fcfb715d76880a813f337a2b5e6aa5e534acead1eb71427`，bridge `edit-docx.mjs` SHA256 为 `432a410c5550be7305eb24ec9428584f4fb1ec5d916189e4a2051f7f3c1f6e2d`。脚本对每个实际加载的 JS/CSS 响应逐文件与冻结磁盘 SHA 对照。

## 其他验证与边界

前端正文修订闭环定向 Vitest 11 项通过；设置 operation 的 Python host 用例 `test_track_revisions_setting_toggles_and_reopens_without_changing_other_parts` 1 项通过。namespace/保护边界的定向 host 复核为 3 项通过。未重复全量测试。

早期 `verified` 目录中的失败保留为过程证据：一次失败由 collector 漏带 `setTrackRevisions` 导致 payload 不匹配，另有临时静态资源路径、端口占用和测试夹具清理问题；这些不是当前冻结构建的通过依据。

本次浏览器 API 使用 fixture route，不能证明生产 HTTP、授权文件接口、桌面 Word 或真实下载签发链。复杂段落/表格/已有修订、接受/拒绝修订和作者/日期交互仍按当前 gap 保留。

## 字体度量分包后的受影响路径续验

为收敛预算，纯数据 `stand-in-boxes.json` 与已有字体度量表并入 `native-docx-font-metrics`，没有改文档逻辑。新的冻结资源为 `/tmp/office-parity-convergence-20261113/static`，manifest `404da158e5e37f9f91eb72244369e8c3dcb791642d7e29096ee6b3c66a00141b`。相同专项在新资源上完成开／关两次保存下载重开，`/tmp/docx-track-revisions-convergence-20261113/result.json` 为 `ok=true/errors=[]`，真实加载新主入口、engine和字体度量chunk。

root 独立再次读取两份下载的SHA、ZIP文件集合、设置值和变化部件：修订2开启，SHA `3782f66d637fbcf14bafdb3a90127d6346f0cdce2e8f0af14f4aa082e74c890c`；修订3关闭，SHA `a2ba62a31e24c0bdea15befd46f3ca9b8569d0572d1f9d5bd463c9cd36322cbb`。两次仍只变化settings和core；没有把ZIP目录条目当作文件身份。日志及结果归档于持久证据根 `convergence/word-browser/`。该脚本成功路径不落截图，不宣称已有新构建成功截图；原有夹具与生产链证据边界不变。
