# Word 单元格九宫格对齐验收

2026-11-10。本项已完成下述专项验收，全量 Word/XLSX 对齐目标继续开放。固定源归属、18 个真实源组合和协议设计见 `NATIVE_WORD_TABLE_CELL_ALIGNMENT_INVESTIGATION.md`。

严格 `setTableCellAlignment` 六字段矩形步骤绑定源 block/hash。九按钮共享组合操作，选中逻辑 slot 后去重 owner；水平只改 owner 的直属 paragraph/list，垂直覆盖 owner 及物理 continuation。隐藏续格段落、嵌套内容、段落 runs/rsid、网格和行高保留。来源段落类型与显式、推断、样式继承 RTL 从可信解析模型取得，不接受客户端 bidi/XML。人工 PM heading 按源命令保留；实际来源 Heading1 在表格 converter 中仍为 paragraph，按其真实语义处理。

前端投影、collector、草稿回放、同表混编守卫、Python 白名单与 bridge 实际回读已接入。对齐无节几何依赖，独立页面设置可同批。XML 只补直属 `tcPr/vAlign` 与目标直属 `pPr/jc`，新标签遵循属性顺序并保留修订标签。

## 已核验

- core 2、project 2、旧投影互斥 1；UI 5 与类型检查通过。
- bridge 基础 3（含九组合真实 DOCX 保存）、可信 converter 对照 1、jc start/end 别名 1 通过。独立复核发现垂直属性插在修订之后，新增 cellIns 顺序用例先 RED 后 GREEN；原修订字节保留。
- 生产范围 types `/tmp/cell-alignment-production-types.log` exit0。初 `/tmp/cell-alignment-types.log` 包含测试引入的完整源 renderer 和未配套路径，不是通过证据。
- Python `/tmp/word-cell-alignment-python-green.log` 首轮 8 通过、1 用例因空 pPr 的测试假设失败；修正测试后仅重跑九组合用例，`/tmp/word-cell-alignment-python-nine-green.log` 1 通过。合计 9 项通过，包含合并续格保留、显式/推断 RTL、非法步骤、身份/保护、独立页面设置与同表原子冲突。
- `/tmp/word-cell-alignment-bridge-build.log` exit0；统一 frontend `/tmp/office-cell-alignment-build.log` exit0（40.40s）；budget 与 budget-contract exit0，未提高预算。没有重复完整测试。
- 独立四个真实 DOCX 边界复核发现 `<w:p/>` 缺 pPr 时插入层级错误；`/tmp/cell-alignment-empty-red.log` 复现，最小展开该段落后 `/tmp/cell-alignment-empty-green.log` 实际保存回读通过。修复后 bridge `/tmp/word-cell-alignment-empty-bridge-build.log` exit0。其他未知 pPr/域、三行合并续格与 SDT 明确拒绝符合预期，证据 `/tmp/cell-alignment-independent-review/REPORT.md`。

## 浏览器验收过程与最终证据

真实 Chromium 首轮在保存修订 2 后发现 probe 对 inferred RTL 的 XML 预期错误，修正 oracle 后第二轮 `/tmp/word-cell-alignment-built-smoke-final.log` 在修订 3 后的 top-right 步发现实际 computed 仍有 center，正在定位修复。完整 12 次公开保存、下载、新修订重开、九组合实际布局及源 XML 保留尚待通过。脚本为 `frontend/smoke/docx-table-cell-alignment-built-smoke.mjs`。此处不宣告浏览器通过；授权/修订替身也不能证明生产 HTTP 或桌面 Word/PDF 等价。

最终 `/tmp/word-cell-alignment-migrated-built-smoke.log` exit0、ok=true/errors=[]；实际使用新 doc_engine bridge。普通九组合和复杂合并三组合共 12 次公开保存、真实 Python patch、HTTP 下载、ZIP 身份与新修订重开通过，Undo/Redo/draft 精确恢复。computed 水平视觉方向和真实垂直 top<center<bottom 均通过；仅 mask 直属 jc/vAlign 后整份 XML 字节、所有其他 OPC 部件及 cell 身份保持。产物 `/tmp/docx-cell-alignment-built-rHNpVF/`，root 目视 revision-33-alignment-reopened.png 确认合并格底端靠右布局。

浏览器缺陷以最小显示适配解决：editable cell 不再把首段 legacy cell.align 作为整格继承样式，而用 start 基线，各段保留自身有效对齐和方向。新 5 项真实 editor render 测试与独立 Chromium 原失败 DOM 复核通过，保存重开也生效；vendor 本地 hash 与 SOURCE 已更新。自闭合段落追加 Python 真实桥接回归通过，合计 Python 10 项（按新/失败范围执行，未重复完整套件）。

统一构建 `/tmp/office-doc-engine-migration-build.log` exit0（40.76s）；XLSX 新分页模块导致主 chunk 超预算，已另拆独立 chunk，待后续统一构建确认，不将该预算失败称作通过。完整 Word/XLSX 目标仍开放。
