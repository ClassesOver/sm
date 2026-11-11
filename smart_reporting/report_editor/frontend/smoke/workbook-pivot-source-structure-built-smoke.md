# XLSX 透视表来源行列结构保护 built 验收

只启动 port 4240 的 vite preview，使用当前已构建 assets/bridge；执行前须等集成人员统一构建通知。脚本不构建、不改生产、不重复 Word 或其他测试。

```bash
node smart_reporting/report_editor/frontend/smoke/workbook-pivot-source-structure-built-smoke.mjs
```

可用 `PIVOT_STRUCTURE_SMOKE_PORT` 覆盖端口。Playwright 新建空浏览器上下文，显式授予 clipboard-read/write；通过 goto 与原生 Ctrl+C 等待本次 sentinel 被覆盖，采集 Source!A1:C5 数据矩阵，不读取生产私有 runtime，也不增加调试后门。

复用现有真实 openpyxl pivot fixture 结构，包含 Source、Pivot、Unused；Source 为 pivotCache 的 worksheetSource，Unused 有固定二维数据。通过 Home 的实际四个结构命令分别尝试插入/删除行、插入/删除列，等待明确“透视表仍读取来源”拒绝反馈，断言 Source 原生复制矩阵、完整 localStorage、保存状态、File undo/redo可用性不变且未发保存请求。命令按钮必须 enabled 且真实点击，不将 disabled 当作原子拒绝证据。另实际尝试 undo/redo，数据与状态仍不变。

Unused 的行插入允许→undo/redo→列插入允许→草稿刷新恢复→公开save→真实 Python `patch_office`→实际浏览器 XLSX 下载→ZIP/openpyxl 验证→明确修订2 URL 重开。断言仅 Unused worksheet XML 改变，Source/Pivot 数据与 sheet、全部 pivot/cache parts、styles 与其他所有 ZIP parts 字节保留，下载 SHA匹配；JS响应200且SHA匹配本地构建，console/pageerror为空。

证据分层：built 断言公开UI的数据矩阵与history/草稿/保存态外证，不宣称读取了内部完整Workbook snapshot；`getSnapshot` 与 `IUndoRedoService` 内部原子性由本轮前端真实 main 单测单独覆盖。路由仅替代授权与修订存储，Python文件补丁、pivot/cache/ZIP回读为真实项目实现。

脚本完成 Node 语法与嵌入 Python compile 检查，并在 root 修复后统一构建上完成最终 built 实测，退出码0。失败留存截图/HTML及stage；成功输出临时目录、精确操作、源/下载SHA、真实parts检查与构建资源身份。

## 最终实测与失败分类（2026-11-10）

- 首轮 session `24089`，`/tmp/pivot-source-structure-built-smoke.log`，exit1：真实 Home 插行命令被底层拒绝后，facade吞false使Ribbon误标dirty并覆盖拒绝反馈。属于生产契约问题；root新增真实Ribbon回归RED→GREEN并修复统一预检，重新构建，原smoke断言未放宽。
- 修复构建后的 session `93063`（`/tmp/pivot-source-structure-built-smoke-rerun.log`）与显式acceptDownloads后的 session `10814`（`/tmp/pivot-source-structure-built-smoke-download.log`）均完整通过四拒绝/状态/Unused/草稿/Python保存与ZIP检查，仅Playwright route拦截下载发生 canceled。独立无工作簿逻辑的标准a download最小复现仍canceled且route未触发，归为probe下载环境。
- 最终仅改probe下载fixture为随机端口的 `127.0.0.1` 临时真实HTTP endpoint，保留公开链接真实点击、`Download.path` 与SHA验证，`finally`关闭endpoint，无生产改动。
- 最终命令：`node smart_reporting/report_editor/frontend/smoke/workbook-pivot-source-structure-built-smoke.mjs > /tmp/pivot-source-structure-built-smoke-http.log 2>&1`；session `70867`，exit0。完整JSON在该日志，产物/下载XLSX/重开截图及HTML位于 `/tmp/pivot-source-structure-built-zViXQb/`。
- Chromium `140.0.7339.16`；Source四种enabled命令原子拒绝，Unused插行/插列及undoRedo/草稿刷新/实际Pythonpatch/实际下载/明确修订2重开全通过。342个JS响应200且SHA匹配本地构建，`errors=[]`。
- ZIP仅 `xl/worksheets/sheet3.xml` 改变；Source/Pivot内容、透视缓存及表定义/关系、styles与其余全部parts字节保持。
- `sourceSha256`：`7f10e615423ea2936a39cabb996b087dadd229e50b199f5d049ebc161933cfbb`。
- `downloadedSha256`：`e8bdaa3c8e11e314e77f646968da958579c9b3e7b6bc7400cbec3ccca41c96ff`。
