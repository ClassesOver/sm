# Word 单格边距覆盖与恢复继承验收

2026-11-10。本专项已完成定向及真实浏览器验收；全量 Word／XLSX 对齐仍未完成。源码事实与真实探针见 `NATIVE_WORD_CELL_MARGIN_OVERRIDES_INVESTIGATION.md`。

本项独立于 Ribbon 整表默认边距：选中单格或矩形后，设置全部四边显式覆盖，或者删除各物理单元格的直属 `tcMar`，恢复原样式／行／表格继承。合并续格隐藏内容必须保留。来源快照区分主格 `rawPresent`、全部物理格 `hasPhysicalOverrides`、`raw`、当前 `effective` 和恢复后的 `resetEffective`；不能把当前 PM 中的继承值误认为显式覆盖。

协议为 `setTableCellMarginOverrides`，携带来源 blockId、expectedObjectSha256 和有序矩形 steps。每步包含 top/left/bottom/right 及 margins；margins 为完整四边整数 twip，或 null 表示恢复继承。服务器必须自行产生可信继承基线，不能接受请求自报快照。同表其他类型修改先保存后继续，独立页面布局可同批。

验收顺序：

1. 固定来源真实向量、core／projection 和 bridge 定向测试，覆盖继承、空容器、部分覆盖、RTL、合并续格及严格字段。
2. UI 单格／矩形／整表选区、混合值、无操作提交、连续同类步骤、Undo/Redo、草稿及过期选区保护。
3. Python 真实 DOCX 保存／恢复、未选物理单元格与 tblPr 保真、来源身份、保护及同表批次冲突。
4. 统一前端构建与现有体积门槛，通过后在真实 Chromium 使用实际 Python bridge 保存、HTTP 下载、ZIP 校验和修订重开。

当前证据：新增 Python 主用例已执行，因未提供 `tableCellMarginOverridesEditable` 明确失败，确认原有能力缺口。入口、collector、草稿和 Python 白名单正在接线，独立 core／bridge 与 UI 由子 agent 并行实施。未重复完整测试，不以此文档或接口接线代替运行验收。

## 定向验证记录

- 独立 core／projection 4 项通过：`/tmp/cell-margin-overrides-final-green.log`。
- bridge 7 项通过：`/tmp/cell-margin-overrides-bridge-final-green.log`，包括多表批量 reset 基线与单 owner 真实 parser 参考等价、空 tcMar、只有隐藏续格存在覆盖的情况。
- UI 初始 6 项通过；续格独有覆盖导致 reset 误抑制的新增用例先 RED，再修复并连同 reset／混合／collector 4 项通过：`/tmp/word-cell-margin-overrides-hidden-ui-{red,green}.log`。表格／Ribbon 窄回归 6 项通过。
- Python 真实 DOCX 10 项通过：`/tmp/word-cell-margin-overrides-python-final-green.log`，23.73s。涵盖显式覆盖／恢复、行继承、合并隐藏内容与非目标 ZIP 部件、无主格覆盖的续格重置、非法值、来源身份、保护及独立页面布局。
- 旧投影互斥回归 8 项通过：`/tmp/word-overrides-projection-regression.log`。
- 最终 bridge bundle exit0：`/tmp/word-cell-margin-overrides-final-bridge-build.log`；前端完整 TypeScript 检查 exit0：`/tmp/office-overrides-trace-final-types.log`。

早期 Python 合并用例因比较 ZIP 目录条目误报，已改为比较全部非目录部件集合及其字节，单项通过；新增 physical 状态后又执行上述最终 10 项。未重复完整测试。统一 build／体积检查、真实浏览器验收及只读集成 review 仍待完成，当前状态仍是实施中。

## 浏览器与最终核对

统一前端 `/tmp/office-overrides-trace-build.log` exit0（Vite39.79s），budget／contract exit0，未提高门槛；Wordmain160.6KiB，render709.9KiB。只读集成 review 另以两张表逆序修改、其他段落插删的真实 DOCX 探针验证索引变化，`/tmp/cell-margin-overrides-integration-review/result.json` 为 passed=true。

实际 Chromium 首轮普通来源已完成修订2保存、下载、ZIP及重开，产物 `/tmp/docx-cell-margin-overrides-built-us3sxn/`。随后样式夹具错误假定直属样式tcPr进入cell effective，预检失败；保留 `/tmp/word-cell-margin-overrides-built-first.log`，未修改产品或放宽right151断言。将夹具改为固定源码实际支持的 firstRow tblStylePr+tblLook 条件继承，并以真实inspect确认resetEffective四边后，仅续跑剩余来源。

续跑 `/tmp/word-cell-margin-overrides-built-smoke.log` exit0、ok=true、errors=[]，产物 `/tmp/docx-cell-margin-overrides-built-ZNUz4R/`。样式／行继承、仅隐藏续格有覆盖的合并表、bidi／竖排三来源分别4／5／4步，保存修订11／21／31；混合矩形、无操作、连续set/reset、Undo/Redo、草稿、实际Python保存、HTTP下载SHA、ZIP及修订重开通过。继承主格reset padding左2.733px（41twip）／右10.067px（151twip），set后左8.667px／右11.733px；合并续格隐藏正文及非tcMar XML、非目标部件保留。121个实际JS资源HTTP200及磁盘SHA匹配。

root目视修订11截图 `revision-11-overrides-reopened.png`。普通来源完整证据由smoke文档索引；浏览器授权／修订路由为夹具，本证据不代表生产HTTP、桌面Word／PDF等价。当前仅单格边距专项闭环，完整表格属性页及全量对齐目标继续开放。
