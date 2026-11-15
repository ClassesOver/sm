# Word 来源单元格合并与拆分

固定对齐源：`f8c17004fb730df11f0f743164ffd8b4281bb38c`。设计依据见 `NATIVE_WORD_MERGE_SPLIT_INVESTIGATION.md`。全量 Word/XLSX 对齐目标仍开放。

## 协议与实现

服务端 inspect 独立签发 `cellShapeEditable/cellShapeReadOnlyReason`、整数 `cellShapeWidthsTwips` 与可见格逻辑矩形 `cellShapeCells`。已有行列增删能力不被放宽，原物理 `cellId` 语义不变。

`reshapeTableCells` 仅接受 `blockId/expectedObjectSha256/steps`。步骤为 `mergeTableCells(rect)` 或 `splitTableCells(rect,rows,columns,mergeFirst)`，rect 零基、右下排他，逐步坐标。最多 50 步，100 行、30 列、1000 逻辑槽，每步核验。保护文件、跨 span 的部分矩形、伪造来源、未知字段及同表其他操作均拒绝。不同表可独立编辑。

共享核心复用 PM mergeCells 与固定源 splitCellsInto 最小纯闭包，整数 twip 分配避免累计舍入漂移。来源默认拆分为 1 行 2 列，先合并；2×2 合并格默认拆分后仍有两个 rowspan=2 格。显式 2×2 才得到四格；内容保留于左上，不恢复合并前文字分布。

前端通过非渲染 `nativeTableCellShape` 意图采集、草稿重放及全投影比对，避免未登记文字或格式混入。宿主将 DocTableRow 的 content 改为 `*`，允许全宽 rowspan 覆盖的空 PM 行；原 `+` 会在合并时补出多余格。保存锁和嵌套输入守卫保留，结构变化后不再向宿主上报旧单元格身份。

桥接只接收受控步骤，以真实源构建最小 PM 模型，原段落 XML token 随内容流转。生成器提供结构壳，原 tcPr 只外科更新 tcW/gridSpan/vMerge，原段落、原行属性和未变格完整 XML 保留；新空段只继承段落属性。实际 ZIP 写出后 parseDocx 回读并检查整表 XML、网格、宽度、段落。

## 定向验证

- core：9 项通过，`/tmp/docx-shape-core-final-green.log`。
- collector/replay：先因不支持协议失败，再 2 项通过，`/tmp/word-cell-shape-collector-{red,green}.log`。
- UI：9 项通过，完整 2×2、来源合并格、对话框、撤销/重做、草稿及锁；`/tmp/docx-cell-shape-ui-{red,green}.log`。
- 原行列操作兼容 31 项通过，`/tmp/docx-cell-shape-ui-compat.log`。Ribbon 旧字体预期缺三款已实现字体，修正预期后该唯一失败项通过，`/tmp/word-cell-shape-ribbon-font-expectation.log`。
- Python 真实桥接：首批 6 项通过，追加横/纵合并、扩网格、连续步骤、保护与旧身份 5 项通过，日志 `/tmp/word-cell-shape-python-{green,additional}.log`。
- 独立复核发现非目标主题底纹/边框被生成器改写，已加 RED→GREEN；pretty XML 格间空白另加回归，bridge 专属最终 7 项通过。完整原段落及未变格 XML 字节保留有直接断言。
- 最终前端构建 `/tmp/office-word-cell-shape-final-build.log` exit0，budget/contract 同前缀 exit0；render 709.9 KiB、main 158.6 KiB、纯来源 helper 3.5 KiB，未提高预算。最终 bridge `/tmp/word-cell-shape-bridge-final-bundle.log` exit0。

最终 Chromium built smoke `/tmp/word-cell-shape-built-smoke.log` exit0：真实拖拽选满 2×2、Ribbon 合并、撤销/重做、默认拆分和显式 2×2、草稿刷新、公开保存、真实 Python patch、实际下载、ZIP 回读、明确 revision2 重开均通过。另将实际合并后的 DOCX 作为独立来源 revision10 打开，拆分保存并明确 revision11 重开通过。119 个不同 JS 文件均校验 200/SHA，errors=[]；全部 12 个原段落 XML 片段及阅读顺序保留、表外 XML 与所有其他 ZIP 部件 SHA 相等。产物 `/tmp/docx-cell-shape-built-nEvW2o/`，root 已目视检查 `revision-11-reopened.png`。详细 probe 说明见 `frontend/smoke/docx-cell-shape-built-smoke.md`。

本次 context/revision/save HTTP 使用替身路由，实际浏览器、下载、Python patch 和 ZIP 均真实执行；不能据此声称生产 HTTP、桌面 Word 或 PDF 等价验收。

## 保留缺口

复杂 continuation（隐藏文字或特殊属性）、嵌套表、修订、字段/绘图/书签等不在本批来源准入范围；同表合并拆分与文字/格式/行列增删/重复标题行需先保存再操作。自动宽度、复杂网格与更深嵌套仍需继续补齐。不宣称桌面 Word 或 PDF 排版等价。
