# Word 合并/拆分 built 浏览器验收

运行前由集成人员完成当前源码的 frontend build 与 bridge bundle。脚本自己只启动 port 4239 的 vite preview；不会构建或运行全量测试。

```bash
node smart_reporting/report_editor/frontend/smoke/docx-cell-shape-built-smoke.mjs
```

依赖项目 `.venv/bin/python`、Playwright Chromium 和当前构建。可用 `REPORT_EDITOR_CHROMIUM_EXECUTABLE` 指定 Chromium，`DOCX_CELL_SHAPE_SMOKE_PORT` 覆盖端口。

脚本在 `/tmp/docx-cell-shape-built-*` 自行生成真实 DOCX：固定 2×2 表、奇数 twip 列宽、原段落 rsid/pPr、混合粗体颜色/斜体 runs、中文 emoji、多段及尾空段、主题填充与表外前后段落。无需外部 fixture。

验收主线：真实鼠标跨格拖拽选中 2×2 → Ribbon 合并 → 撤销/重做 → 拆分对话框默认 1×2（确认仍各跨2行）→ 撤销 → 显式2×2 → 草稿刷新 → 公开保存 → Python `patch_docx` → 浏览器实际下载 → ZIP 回读 → 修订2重开。另一条从 Python 真实生成的已合并来源重新 inspect/Open，显式2×2拆分保存、下载及重开，证明已存在合法 span 来源可编辑。

路由仅替代认证与修订存储；inspect、patch、DOCX/ZIP 均走项目真实 Python/bridge。严格比较全部原段落 XML 片段及顺序、表外 document XML、所有其他 parts 的 SHA256、网格 widths/rect，并核验浏览器 JS 响应200及其 SHA与本地构建相同，console/pageerror为空。最后输出 JSON 证据、源码/下载 SHA、操作协议及临时目录，保留截图与 HTML；失败保留 failure.png/html 并报告 stage。

编写阶段完成 Node 语法及嵌入 Python compile 检查。收到 root 当前 frontend build 与最新 bridge bundle 完成通知后，已执行一次最终 built 验收，退出码 0。

## 最终 built 实测记录（2026-11-10）

- 命令：`node smart_reporting/report_editor/frontend/smoke/docx-cell-shape-built-smoke.mjs > /tmp/word-cell-shape-built-smoke.log 2>&1`。exec session `24769`，最终 exit 0；Chromium `140.0.7339.16`。
- 完整 JSON：`/tmp/word-cell-shape-built-smoke.log`；fixture、修订1/2/10/11及实际下载、截图与 HTML：`/tmp/docx-cell-shape-built-nEvW2o/`。
- 真实鼠标选区、Ribbon合并、撤销/重做、默认1×2（两个rowspan=2）、显式2×2、草稿刷新、公开save、真实Python patch、实际浏览器下载、ZIP回读、修订2重开全部通过。独立已合并来源修订10打开、拆分、保存下载及修订11重开同样通过。
- 原12个段落片段及顺序逐字一致，表外 document XML 与其他所有 parts SHA一致，网格宽度/rect正确；加载JS响应200且SHA匹配本地构建，`errors=[]`。
- `sourceSha256`：`5966eaab3f791ed966f604c7550caacead2b50a7d4609c9f2a2835edd0bf3962`。
- `downloadedSha256`：`242ca57b016c6413810e99778a67180f88e8a867d401e193287656c68f73f53a`。
- `mergedSourceSha256`：`59b3380e20c1ffd3a4e3aff558955d274e40752595d919e30b280fcfb530e229`。
- `mergedDownloadedSha256`：`50ae44b67754bb1a746ac4a95271fcbb289070f04457e7220cb5c20f053c0b16`。
