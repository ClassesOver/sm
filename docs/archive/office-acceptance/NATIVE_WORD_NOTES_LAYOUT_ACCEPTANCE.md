# Word 正文、注释与段落布局同批保存

2026-11-10。本批处理同一来源段落修改正文、插删脚注尾注后，同时调整已支持段落布局被拒绝的问题。保留既有普通 `editable`；新增 `paragraphLayoutEditable` 专用能力，只开放对齐、左右缩进、段前/段后和倍数行距。

前端在已核验的 notes-safe 来源上，用无正文投影复用原 `docxOperations` 布局校验。布局操作和来源 run 片段计划分别生成；无布局变化的注释编辑不受布局只读能力影响。草稿回放四类布局操作统一校验原 block/hash、专用能力和字段白名单。后端只为这四类开放 notes-safe 段落，并在同一原始 pPr、run 来源上合成；不接受客户端 XML。

固定源行为依据：f8c17004 的 `renderer/editor/direction.ts:101` `setSelectionAlign` 和 Ribbon 的缩进/间距处理独立修改段落 attrs，不因 note marker 禁用。原固定源算法及当前普通布局值域保持不变。

已验证：

- 新前端正向与身份回放契约 18 例；独立布局投影 12 例及专用只读能力 1 例。
- 新后端 11 例，包含原文改字+新注释、既有 note 的只读正文来源、多个布局值合成、pPr.keepNext/run.noProof 保真和非布局混编拒绝。
- 既有相关前端 7 文件共 171 例；首轮 169 通过，两个旧 fixture 分别补齐正确来源 hash、匹配专用底纹只读原因后，只重跑对应 2 例通过。
- 既有 notes/inline 后端 39 例通过；未运行完整测试。
- TypeScript `--noEmit` 通过；构建和预算由 root 统一执行。
- Chromium 140 的 `DOCX_INSERT_CASE=notes-layout`：既有 footnote 段落前后改字、新增 endnote、四类布局、撤销/重做、草稿刷新、两次实际 patch_docx 保存下载重开通过。第二次仅修改布局并 updateNote，未生成多余正文 run 计划。页面错误为空。

浏览器入口使用替身 context/file/preview 路由、真实 Vite 主视图和 Python/bridge 保存；不代表真实 AgentOS 服务、Office 桌面或完整 Word 对齐。

证据：`/tmp/word-notes-layout-front-red.log`、`/tmp/word-notes-layout-back-red.log`、`/tmp/word-notes-layout-existing-back-red.log`、`/tmp/word-notes-layout-replay-identity-red.log`、`/tmp/word-notes-layout-front-green1.log`、`/tmp/word-notes-layout-back-green1.log`、`/tmp/word-notes-layout-related.log`、`/tmp/word-notes-layout-related-two-green.log`、`/tmp/word-notes-layout-back-related.log`、`/tmp/word-notes-layout-types.log`、`/tmp/word-notes-layout-gui-green1.log`。

边界：段落样式切换、列表结构、分页、段落边框/底纹、清格式及复杂内联对象改写仍不能与同段 notes 正文改写混用。表格内及不具备 notes-safe 来源能力的对象不因本批变为可编辑。
