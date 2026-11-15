# PDF 静态 Fill Form 验收（2026-11-13）

本次交付为静态填写完整组件族：文字、勾叉、印刷方框吸附、原生 checkbox 命中、保存后重编、原来源页内移动/尺寸调整/删除、取消与真实草稿 UndoRedo、必填软提示，以及实际导出和独立回读。静态文字和标记直接加入页面，不创建可交互的原生表单字段。必填与业务验收告警不会阻断已有 PDF 的保存或下载。

## 来源与实现边界

固定来源 `/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。两个 renderer helper 仅首行纯类型导入替换为实际使用的类型形状，算法正文不变。后端复用固定源 PDFium image insert/matrix/delete 与已有 PNG/BGRA/串行上下文，固定 `save-pdf.ts` reader/writer 负责静态填写 metadata 和页重排/删除映射。详细来源见 `frontend/src/pdf-static-fill-SOURCE.md`。

保存项须由来源 SHA、原页面、metadata id/矩形及实际图像 fingerprint 唯一绑定后方可编辑。输出复核或后续 metadata 序列化失败保留已经生成的真实 PDF 并给出 reviewIssues。三个故障类型已登记到 `test_http_publication_lineage.py::test_static_fill_review_never_blocks_actual_pdf_http_download`。

当前范围为默认 UserUnit、正交旋转、非签名非加密 PDF，可保留普通 AcroForm。静态字为图像内容，不可搜索；已保存项仅原来源页内移动，不声称跨页拖动。metadata 写回失败的保底 PDF 可能无法继续重编。删除属于逻辑删除，涂黑使用现有引擎擦除像素并移除对应静态填写缓存。

## 可回读证据

根目录：`/home/junge/codex-evidence/smart_reporting/office-pdf-static-fill-20261113-recovery`。环境重启前 `/tmp`、`/dev/shm` 证据已经丢失，旧结果不作为本验收可回读依据。`README.md` 与各失败目录保留恢复轨迹。

| 验证 | 结果与证据 |
|---|---|
| 静态填写与 Ribbon 定向测试 | `frontend.log`：23 通过 |
| 真实内容图、重编/删除、页序映射、身份/旋转、读回及 metadata 软失败 | `bridge.log`：6 通过 |
| 三类故障仍可 HTTP 下载及签发守卫 | `http-nonblocking.log`：4 通过 |
| 涂黑缓存与实际像素擦除 | `redaction-green.log`：1 通过；保留 ImageObj 但原像素清成白色 |
| 宿主已保存记录接线 | `reopen-host-green.log`：1 通过；真实复开先在 source-native-04 暴露遗漏 |
| 源码真实闭环 | `source-native-05/independent-readback.json`：两轮真实保存下载/复开修改回读通过；runner末尾因 Vite 开发 WebSocket 控制台错误失败，不宣称整体绿色 |
| 冻结 v4 严格真实闭环 | `frozen-native-01/evidence.json`：退出 0，页面/控制台/HTTP 错误均为空；低高度截图随后发现底部按钮裁切，另作专项修复与零保存续验 |

## 冻结资源、后端身份与实际下载

v4 前端快照为 `/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113/source/smart_reporting/report_editor/static`，manifest SHA256 为 `96be3d8e01bc69c68f42693a20f81712ff47614e94e9194a4c9856ba4b8d5b94`。`frozen-native-01/evidence.json` 记录 65 个实际 HTTP JS/CSS 的字节摘要，全部与冻结磁盘文件一致，manifest 与前端源码摘要前后不变。

PDF 引擎为本批隔离构建的 `frozen-runtime/dist/cli.mjs`，SHA256 `496cf8815ca47097da05ea5a3863ca8708db1cf5a56532fd80f7a93625f5cb8f`，7,440,649 字节。`frozen-runtime-source-equivalence.json` 证明实际 metafile 的 255 个非 npm 输入均位于冻结副本，与统一源码快照摘要一致，没有解析 live 本地源码；713 个 npm 输入与两份固定 WASM 另有摘要。运行无需 live TS 源码或 node_modules。

真实 Python 授权、修订、发布和下载链使用现有宿主，不能把它说成完整冻结 Python 包。`frozen-native-backend-before.json` / `after.json` 记录 288 个实际宿主相关 Python 文件、bundle 与 WASM 的起止摘要相等；统一快照内 292 个 Python 文件与 live 同名文件逐一相等。

| 实际产物 | 大小 | SHA256 |
|---|---:|---|
| 首轮修订 5，`frozen-native-01/downloaded.pdf` | 21,278 B | `eb48ee168c958d09088cad3e071c7f71872bf670097b0b3adc6ff832b2de2c7a` |
| 复开编辑后修订 6，`frozen-native-01/downloaded-edited.pdf` | 19,406 B | `ae465c68d7b6748ecc3d6ea7c7d09aa254d597e2834319ae14c444932eb19143` |

两次均使用真实授权、CSRF、预览确认、修订登记与 HTTP 下载，下载字节大小/SHA 与签发身份一致。`independent-readback.json` 用 pypdf 证明静态记录与实际内容图 3→2，透明 alpha masks 3→2，修改后的中文值、勾号矩形 `[75,340,95,362]`、原正文/页框、原生字段集合保留；`NativeCheck=/Yes`，原必填文本仍空。无 Stamp。原件 SHA256 `c7a02d664e92d35bde800a70224c9c10dd5a7d59f8fbf6148a2832bdd8eb9ad0` 不变。

两轮 `validation.ok=false`，明确保留 `native_source_review_pending`；这是技术编辑/下载链通过，不是业务事实或完整排版验收通过。

## 低高度修复续验

最终目视发现 1024×480 的窗口按钮被通用 `overflow:hidden` 裁切。修复仅给本族三个窗口增加 `pdf-static-fill-dialog`，并用专用规则 `overflow-y:auto` 开放滚动，不改其他 PDF 窗口。`pdf-static-fill-layout-smoke.mjs` 复用以上真实第二轮下载，以零保存方式验证实际鼠标滚轮改变 scrollTop、底部更新/取消按钮在视口内且通过 elementFromPoint 命中，以及 390×844 无横向溢出。最终 v5 回执见下，修复已经通过。


最终 v5 静态资源为 `/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113/source-v5/smart_reporting/report_editor/static`，manifest SHA256 `11c248ae3a4c6fa31fad99f04d2e72437abc4440569e1d846615616b7f442e17`。统一构建、类型检查与原体积预算由主任务验证通过；PDF main 低于既有 250 KiB 上限，未抬预算。

`frozen-v5-layout-01/evidence.json` 的正式续验退出 0：重新授权打开 v4 的真实第二轮下载（SHA `ae465c68d7b6748ecc3d6ea7c7d09aa254d597e2834319ae14c444932eb19143`），读取两条可编辑填写与已保存中文，`savedRevisions=0`。65 个实际 HTTP JS/CSS 与 v5 冻结文件摘要相同；页面、控制台与 HTTP 错误均为空，manifest 前后相同。1024×480 窗口 clientHeight 446、scrollHeight 464、overflowY auto，真实 wheel 后 scrollTop 增长；更新原位置与取消按钮的中心均可由 elementFromPoint 命中且完整位于视口，取消关闭窗口。`1024x480-wheel-bottom.png` 已目视。390×844 无横向溢出。

`frozen-v5-backend-before.json` / `after.json` 记录宿主 Python、两个更改的前端产品文件、PDF bundle/WASM 起止摘要一致。`frozen-runtime-v5-equivalence.json` 再次证明同一 PDF runtime 的 255 个非 npm 输入与 v5 快照一致；无需重建引擎。产品最终 SHA：`pdf-static-fill.ts=abd2f6b8d98e9c3bf7c00dbfb1ae9d2865c96e3b04af9c0be1f4283dace354e9`；`pdf.css=6924083957182b58df6b0bf85fcefcadc86f8d002d80119ee697be041276574e`。

验收分层：v4 证明两次实际保存/下载/复开重编与独立产物回读，v5 证明最后的局部滚动修复及该真实下载重新打开。没有用 v5 零保存续验冒称重新执行了两次保存，也没有重复全矩阵。源模式 `layout-source-01` 因 runner 丢失 Vite `?url` 查询参数失败，修正后 `layout-source-02` 局部滚动通过；正式结论以 v5 冻结回执为准。
