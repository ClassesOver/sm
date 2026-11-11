# DOC 引擎

DOCX 原生读取和编辑的独立引擎，与 `slides_engine`、`workbook_engine`、`pdf_engine` 同级。

```text
doc_engine/
  bridge/                # edit-docx CLI 和宿主编辑适配
    tests/               # DOCX 桥接定向回归
  packages/docx-engine/  # 固定 GenOffice DOCX 包、测试和来源文件
  probes/                # 原生表格调查工具
  dist/                  # 构建生成 edit-docx.mjs（不提交）
  package.json
  package-lock.json
  SOURCE.md
  LICENSE
  NOTICE
```

在本目录执行 `npm ci`，执行 `npm run bundle:bridges` 生成独立 Node 桥接。桥接复用宿主前端的表格投影 core，因此开发构建前也须在 `../../report_editor/frontend` 执行 `npm ci`。共享的 PPTX、agent-core 和 ZIP 包通过同级 `file:` 依赖复用；PPTX 公式与过渡适配也继续引用本目录的数学/XML 工具，无重复源码。

Python 使用 `run_bridge('doc', 'edit-docx', request)`。默认目录为本目录；部署可通过 `AGENT_REPORTING_DOC_ENGINE_DIR` 指向裁剪运行目录。运行包只需 `dist/edit-docx.mjs` 和许可/来源文件，不需要源码或 `node_modules`。

Docker 按现有 Office engine 方式独立安装、构建、裁剪并复制至 `/opt/reporting-doc-engine`。`docker/package-office-engine.mjs` 根据 esbuild metafile 保留跨目录依赖与 vendor 的许可。

旧 `slides_engine/SOURCE.md` 中 DOCX 条目保留为历史证据，当前归属和迁移说明见本目录 `SOURCE.md`。此迁移只调整组织和运行路径，不表示全量 Word 功能对齐已完成。
