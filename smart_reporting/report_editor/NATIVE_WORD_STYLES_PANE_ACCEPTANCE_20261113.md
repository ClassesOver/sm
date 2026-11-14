# Word 样式窗格专项验收（2026-11-13）

固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的 `StylesPane.tsx`、`StyleDialog.tsx`、`style-gallery.ts` 已形成可操作、可保存、可重新打开的原生 Word 闭环。v4 冻结版本通过 21 项 Chromium 检查，浏览器错误为零；下载 DOCX 经独立 ZIP / python-docx 回读后，原有样式定义、页眉、邻段及表格保持不变。

| 固定源动作 | 已验收行为 |
| --- | --- |
| 面板和样式库 | 当前样式、搜索、推荐 / 全部 / 使用中过滤、段落与字符样式预览 |
| 清除格式 | 复用既有固定源清除格式操作，可撤销 |
| 应用段落样式 | 按源规则移除覆盖超过半段的直接字符格式；支持标题转正文及继承标题样式 |
| 列表段落 | 普通段落样式保留原编号；转换为标题时移除编号 |
| 应用字符样式 | 合并 `styleId` 时保留原始 `rPr`；再次应用当前字符样式按源规则移除整个 `docTextStyle`，保留独立 B/I/U/strike |
| 新建 | 源对话框字段、同名检查、基准样式、实时预览；新建定义和立即应用可同次保存 |
| 修改 | 只合并用户触及字段；未操作确定及取消不产生草稿 |
| 更新以匹配所选内容 | 读取当前选区的直接格式和样式继承后更新定义 |
| 选择所有实例 | 复用源 `styleInstanceRanges` 与现有多选插件 |
| 光标处字符样式 | 先设置 storedMarks；后续输入复用既有来源 Run 计划，草稿恢复后可保存 |
| 历史与范围 | 原生撤销 / 重做、草稿恢复；表格范围和只读修订禁用修改，保护范围不接受应用 |

固定源没有删除样式入口，本次未增加删除动作。同段样式应用与其它正文修改仍需分开保存；同一段可记录连续的样式应用动作。不支持的范围不会伪装为可编辑能力。

样式定义复用既有原生草稿 / 文档事务历史，使用 `styles.xml` 摘要绑定受限 `StyleUpsert`。异步显示继承复用引擎 `previewFontSettings`，保存复用 `saveDocx(...styleUpserts)` 及原生 Run 写入器。未另建 `styles.xml` 序列化实现。对话框绑定打开时的文档和选区，并补充明确可访问名称、输入法键保护与焦点陷阱；三种窗口尺寸的确定按钮均通过真实 `elementFromPoint` 命中检查。

统一物理快照及构建证据位于：

`/home/junge/codex-evidence/smart_reporting/office-styles-media-format-fill-20261113`

| 冻结身份 | 值 |
| --- | --- |
| 前端 manifest SHA-256 | `96be3d8e01bc69c68f42693a20f81712ff47614e94e9194a4c9856ba4b8d5b94` |
| 实际执行 DOCX bridge SHA-256 | `d43ef1bc3129cc4b3f60cbd8b7469b795c6695f50bdfdc11543e23dc6f6dfc6a` |
| 实际 HTTP 下载 DOCX SHA-256 | `aeca0a9e3fbe01c6dfd3174c9e81f9774a1aa570e97d7abd2df65cdfc36b0505` |
| 下载大小 / 状态 | 38,375 bytes / HTTP 200 |
| 冻结浏览器结果 SHA-256 | `07c4037ea48878a2161dc1a0b9382b2a07ab5f79a54936abe375732dcca3267f` |

统一 `build-v4.log` 记录 `tsc --noEmit && vite build` 成功，Vite 耗时 46.86 秒；`budget-v4.log` 的原预算检查通过，未抬高预算。`native-docx-engine` 为 417.3 KiB。样式定义按自然模块 `style-upsert.ts` 单独分块。

`docx-runtime/build-identity.json` 记录 bridge 的 255 个构建输入：124 个物理快照工作区文件、131 个第三方依赖文件。工作区包使用显式快照 exports 映射，并拒绝解析到 live workspace 源码；最终逐输入回读未发现变化。`docx-runtime/metafile.json` 和 `docx-runtime/smoke-receipt.json` 保留构建及独立执行回执。

`styles-frozen/result.json` 记录 21 项最终检查、160 个实际 HTTP JS/CSS 资源摘要，以及实际运行的 Python 桥接入口。Python 薄包装、原生 API 包装及 bridge 源码在浏览器运行前后的摘要一致。下载实际字节保存在 `styles-frozen/downloaded-revision-2.docx`，与修订 2 文件身份一致；随后重新请求修订 2 的 context / file / preview，并从重新解析的画布确认输入文字、段落样式卡及字符样式卡。只读修订的修改入口保持禁用。

独立回读确认新建的 `Report Body` 与 `Report Char`、字体槽、13.5 pt 字号、段后 8 pt、斜体及新增文字的字符样式。旧 `styles.xml` 中每个既有样式定义逐项比较相等；正文非目标邻段、表格、页眉和其它未修改 ZIP 部件保持相等。验收 fixture 返回 `validation.ok=false` 及具体告警时，原生界面仍签发并可下载实际 Word 文件，没有将验收标记为通过。

授权、修订登记和验收结果的 HTTP API 为 fixture；实际冻结前端、Chromium 操作、Python 原生 bridge、DOCX 写入、HTTP 下载、修订重新解析及 ZIP 回读均真实执行。本专项不代表生产鉴权或完整发布服务验收。

定向测试证据位于：

`/home/junge/codex-evidence/smart_reporting/office-styles-20261113-recovery`

- 前端 44 个独立用例：`frontend-contract-adjacent.log` 的 43 个基线用例，加新增范围用例；最终 `frontend-style-final.log` 的 Styles 7 项全部通过。覆盖字体、普通样式、原生历史及清除格式邻接契约。
- 后端 Styles 15 项：`backend-contract.log` 的 13 项，加 `backend-heading-list.log` 的标题 / 列表 2 项；`backend-font-adjacent.log` 的原字体 10 项全部通过。
- 可访问名称及范围保护的 RED → GREEN 日志已持久保存；环境重启前的临时 before 快照、原 RED 日志及共享文件任务差异已丢失，具体记录见 `recovery-note.json`，没有将其冒称为仍可回读证据。

冻结浏览器 runner 使用物理快照中的专项 runner，保留在 `styles-frozen/runner.mjs`。`runner-identity.json` 与 `runner-instrumentation.patch` 记录仅测试路径和下载 / 重新打开回执增强；未改冻结产品代码。复现须提供 `DOCX_TEST_DIST`、`DOCX_EXPECTED_MANIFEST_SHA256`、`DOCX_FROZEN_FRONTEND`、`AGENT_REPORTING_DOC_ENGINE_DIR`、`DOCX_EXPECTED_BRIDGE_SHA256` 和 `DOCX_EVIDENCE_DIR`，实际入口及全部身份在结果中再次校验。


## v5 最终资源续验（不重复完整矩阵）

v4 的 21 项功能验收、保存及独立 ZIP 回读证据保留原身份。PDF 低高度修复在独立 `source-v5` 物理副本构建后，Word 仅追加入口 / 真实下载重开续验，未再次运行完整功能矩阵、未保存新修订。v5 manifest SHA-256 为 `11c248ae3a4c6fa31fad99f04d2e72437abc4440569e1d846615616b7f442e17`。

`styles-reopen-v5/runner.mjs` 读取 v4 实际下载的 38,375-byte DOCX，先断言原下载摘要 `aeca0a9e3fbe01c6dfd3174c9e81f9774a1aa570e97d7abd2df65cdfc36b0505`，再作为修订 2 的来源，通过 v5 HTTP 入口重新读取 context / preview / file。重新解析后的画布包含 `光标Z输入`、`ReportBody` 及 `ReportChar` 样式卡，只读修改入口禁用；保存次数为 0，无 `/save` 请求。继续复用相同 API fixture 边界，不代表新增生产授权 / 修订服务验收。

结果位于 `styles-reopen-v5/result.json`，SHA-256 为 `bc8cfb56124db5c2b9932b8ddf134b74a6938c889cb52affbdc05906b58cda5e`。160 个实际 HTTP JS/CSS 资源与 v5 物理磁盘字节摘要相等，浏览器错误为零；实时 Python 包装及 bridge 源码前后摘要相等。实际执行 bridge 仍为 `d43ef1bc3129cc4b3f60cbd8b7469b795c6695f50bdfdc11543e23dc6f6dfc6a`。`reopen.png` 保存最终画布；`harness-attempt-1-failure.json` 保留首次测试断言误将合法 POST preview 当成保存的失败记录，续验仅修正为检查无 `/save`，产品代码未改。
