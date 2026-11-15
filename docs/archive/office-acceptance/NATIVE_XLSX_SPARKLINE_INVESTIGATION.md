# XLSX 迷你图：固定源能力与最小迁移闭环调查

日期：2026-11-10。固定源 `/home/junge/pros/genoffice-source-full`，实际 `git rev-parse HEAD` 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。调查阶段只读生产代码；随后按 root 授权仅修复本地 `packages/xlsx-engine/src/sparklines.ts` 两个已复现缺陷，并新增独立回归测试（见第6节）。未修改 frontend/bridge/main/Ribbon，未构建 dist，未跑完整测试，未提交或 push。

结论：**固定源有真实新增并持久化的迷你图能力；本地已有读取与显示、未接新增操作协议。仍为本地缺功能。** 本地 `applySparklines` 是整表替换接口，不能把现有对象读成简化 spec 后直接拼接重写作为无损“新增”。下面的初始 ZIP 实验复现了该现成 writer 的扩展插入位置与颜色合并问题；第6节记录它们已修复，原始失败证据仍保留。推荐最小交付为源范围的三类新增，保留已有 raw groups，复用本地渲染与草稿/保存链。

## 1. 固定源实际执行链

路径均相对固定源，使用稳定符号定位。

| 层次 | 文件／符号 | 实际行为 |
| --- | --- | --- |
| Ribbon | `apps/sheets/src/renderer/ExcelShell.tsx`，`sparkline:line/column/stacked` | 三类实际 action，传给 ribbon handler；不是只有标签。 |
| 创建 | `apps/sheets/src/renderer/ribbon-actions.ts`，`case 'sparkline'`（约2153行） | 要求已导入的文件与至少两列；活动表当前选择每行一个源范围，放到选择右侧一列；宿主列检查 grid 上限。类型 `line/column/stacked`。 |
| 会话 | `edit-journal.ts`，`recordSparklineAdd/removeSparklineAdd/toSaveSparklineAdds` | journal 追加 `{id,sheetId,type,color?,cells:[{cell,sourceRef}]}`；撤销移除本会话 entry，重做重新加入；序列化跳过已删除页。源引用由 `absRangeRef(sheetName, range)` 生成表名限定绝对引用。 |
| 显示 | `univer-sync.ts`，`queueSparklineInstall`；`WorkbookVisuals.tsx`，`installSparklines` | 将文件自带 groups 与当前 sheet 的 journal additions 合并；后者通过 float DOM/SVG 显示；编辑后排队重装；按 sheet name 解析 sourceRef，可读取另一表的源数据。 |
| 保存请求 | `save-actions.ts`，`toSaveSparklineAdds` → `saveWorkbookEdits` | `sparklineAdditions` 是真正保存与 recovery payload 字段；`apps/sheets/src/shared/desktop-api.ts` 的 schema 校验它。 |
| 宿主 | `apps/sheets/src/main/sheets-main.ts`，`sparklineAdditions`（约4858行） | 把稳定 `sheetId` 解析为保存目标 `sheetName`，传给 streaming save。 |
| 打包 | `packages/xlsx-gateway/src/gateway/xlsx-package-io.ts`，streaming save | `request.sparklineAdditions` 传入 `planCellEditsToXlsx`，产生 replacement part 后交归档器写实际 ZIP。 |
| 写入 | `xlsx-gateway.ts`，`planCellEditsToXlsx`（约1703行）；`xlsx-sparkline.ts`，`applySparklineAdditions` | 在结构、单元格、table/filter 等 XML 更新之后，按页分组，修改 worksheet part，并登记 touched entry。追加 `x14:sparklineGroup` 到根 `extLst/ext`；已有 groups 留原文，不重建已有对象。 |
| 再打开 | `apps/sheets/native/xlsx-engine/src/sparklines.rs`，`read_sheet_sparklines/parse_sparkline_groups` | 真实文件解析器读取扩展 URI、group type、RGB/ARGB、negative color、source_ref 和 cell；按 XML local name 读取，支持文本、CDATA、实体。`types.rs` → shared desktop schema → file metadata → 上述显示器。 |

源 writer 生成扩展 URI `{05C60535-1F16-4fd2-B633-F4F36F0B64E0}`，`x14` namespace `http://schemas.microsoft.com/office/spreadsheetml/2009/9/main`、`xm` namespace `http://schemas.microsoft.com/office/excel/2006/main`。折线省略 type；柱形 `column`；盈亏 `stacked`。series 默认 `FF376092`，negative `FFD00000`，empty 为 `gap`。同一新增 batch 重复宿主或与原 XML 已有 canonical `xm:sqref` 宿主冲突时拒绝。

不能据此扩大范围：

- 此 Ribbon 是“新增”；没有据现有组改类型、编辑源、删除文件原生组的完整链。
- Ribbon `Math.min(range.getHeight(), 200)` 会截取前200行；CLI `add_sparkline` 则对超过200行明确拒绝。迁移应明确提示／拒绝超限，不静默漏掉选择尾部。
- 源 Rust 读取上限100组、每组500宿主；源显示也有预算。已有大文件读取不是无限完整。
- 源 writer 的重复宿主检查依赖 canonical `<xm:sqref>...</xm:sqref>` 文本，不能将其宣传为所有 prefix/空白形式都健壮；最小实现须 namespace-aware 提取宿主，或对不能可靠识别的扩展形态明确拒绝新增、保留原件。
- 实际执行的是固定源 writer 函数；本轮没有启动 Electron、Rust sidecar 或完整源 streaming save。上面的完整宿主链属于源码追踪证据。

## 2. 本地已有能力与协议缺口

路径相对本仓库根；`X=smart_reporting/reporting/workbook_engine`，`F=smart_reporting/report_editor/frontend/src`。

| 现状 | 证据与复用判断 |
| --- | --- |
| 文件读取已在 | `X/packages/xlsx-engine/src/workbook-read.ts` 调 `readSparklines`，模型 `sheet.sparklines` 可供 UI；`src/index.ts` 已导出该模块。 |
| 画布显示已在 | `F/workbook-vendor/core/univer-data.ts` 把 specs 传下去；`grid/sync.ts` 的 `setSparklines` 初始化；`grid/sparkline-render.ts` 画 line/column/winLoss，读实时当前 worksheet 的数字值，可复用 store 与刷新。该路径没有 Plotly。 |
| 新增 Ribbon 未接 | `F/workbook-ribbon.ts` 三项是无第三个 command 的 `action(id,id)`；`disabledReasons` 明确“尚不能回写迷你图修改”。 |
| 公共操作桥未接 | `X/bridge/operations.ts` 未导入/调用 `applySparklines`，也无 sparkline operation。真实 `/tmp` 桥探针传 `applySparklines` 和建议名 `appendSheetSparklines` 都返回 `workbook_operation_invalid`。 |
| 独立原生宿主许可未接 | `smart_reporting/report_editor/native_office.py` 的 `_XLSX_FIELDS` 无 sparkline 操作。若只加 TS case，独立原生文件保存仍会被顶层协议拒绝。 |
| 历史 AI schema 不等于当前能力 | `F/workbook-vendor/core/session-core.ts` 有 `addSparklines`（整表替换、最多60项），但当前 `workbook-main.ts` 的 collector/bridge 不使用它；当前服务 `workbook_ai.py` 的候选 Literal 也无迷你图。本次不建议为 Ribbon 顺带扩大 AI 能力。 |
| 现成写入函数有不同语义 | `X/packages/xlsx-engine/src/sparklines.ts` 的 `applySparklines` 全量替换该表 sparkline ext。初始版本仅按 kind 聚组，每类颜色与 markers 用首项，showAxis 用组内 any；这些样式混用问题已在第6节修复。全量替换语义与 reader 信息丢失仍不适合重写读入对象后做追加。 |

本地 reader/renderer 的既有边界：reader 用固定 `x14/xm` prefix 与大小写敏感 URI regex；从 `xm:f` 删除表名前缀，渲染只访问宿主 worksheet，因此跨表 source 会被错误地当成同表数据。读取还丢失未知属性、原始 grouping、负色等信息。最小新增可限定同表，但**已有跨表对象的显示不能因此宣称与源等效**；应保留原始引用并解析来源表，或明确不渲染无法正确定位的来源。不要以简化 reader 的输出覆盖原有 raw XML。

结构边界已有保护：`X/.../structural.ts` 的 `assertShiftable` 对 `<x14:sparklineGroups` 拒绝行列移位，避免来源／宿主错位。新会话 additions 尚未进入原始 XML，所以接入时也要覆盖“先新增、后结构编辑”的保护，不能只依赖原件 marker。

## 3. 已执行的真实 ZIP / 独立回读

全部临时材料：`/tmp/xlsx-sparkline-gap/`。可重放：

```sh
node --import /home/junge/pros/smart_reporting/smart_reporting/reporting/workbook_engine/node_modules/tsx/dist/loader.mjs /tmp/xlsx-sparkline-gap/probe.mts
/home/junge/pros/smart_reporting/.venv/bin/python /tmp/xlsx-sparkline-gap/readback.py
node --import /home/junge/pros/smart_reporting/smart_reporting/reporting/workbook_engine/node_modules/tsx/dist/loader.mjs /tmp/xlsx-sparkline-gap/bridge-probe.mts
```

`probe.mts` 直接 import 固定源 `applySparklineAdditions`（未复制／改写源 writer），用本地 blank/cell engine 准备有实际数值的输入，仅用本地 ZIP assembler 包装其返回的真实 worksheet XML。不是通过手工拼装 sparkline XML 证明 source 实现。读取检查既用本地 `readWorkbook`，也用独立 Python `zipfile` + namespace-aware `ElementTree` + openpyxl。没有用 openpyxl 重存产物。

| 实际向量 | 结果 |
| --- | --- |
| `source-written.xlsx`：折线 B2:D2→E2、柱形 B3:D3→E3、盈亏 B4:D4→E4 | 三组在 worksheet 根 `extLst/ext` 下；源引用分别为 `Sheet1!$B$2:$D$2` 等；独立读回类型 line/column/stacked，宿主 E2/E3/E4，RGB 默认正确；ZIP CRC 通过。 |
| 非目标 parts 保全 | input 与源写出所有条目 SHA256 比对，仅 `xl/worksheets/sheet1.xml` 改变。 |
| 已有宿主再次新增 E2 | 源 writer 抛 `E2 already has a sparkline.`；无伪造成功产物。 |
| 源产物再做普通 B2 编辑为9 | `source-written-cell-edited.xlsx` 仍有三组；openpyxl 独立读 B2=9。 |
| 本地 writer 同类型、不同颜色 | 请求 E2 红、E3 绿；`local-written.xlsx` 两条实际都变红，机器结果 `localSameKindColors`。这是实际重放结果，不只静态猜测。 |
| 本地 writer 遇已有非迷你图根 extLst | `local-foreign-extension.xlsx` 的新 sparkline `<ext>` 被写在 `</extLst>` 后，成为 worksheet 直接子节点；独立 namespace-aware 路径匹配不到合法 sparkline groups，`misplaced_root_ext_count=1`。XML well-formed 不能代表 OOXML 位置有效。 |
| 本地 reader 输入跨表 source | 把源 XML 的 `Sheet1!` 改为 `'Other Sheet'!` 后 `readSparklines` 仍只返回 `$B$2:$D$2` 等，来源表身份丢失；本向量只证明 reader 的信息丢失，未冒充跨表文件 GUI 验收。 |
| 当前公共 bridge 传迷你图操作 | `bridge-result.json` 两种名称均返回 `workbook_operation_invalid`；证明尚未接桥。 |

openpyxl 对源合法 x14 产物明确警告 `Sparkline Group extension is not supported and will be removed`：它验证工作簿与普通单元格可读，**不提供迷你图对象回读证明**。迷你图原始类型、位置、引用、颜色的独立回读证据来自 ZIP + ElementTree；不能将该 warning 当损坏或执行 openpyxl save（会丢扩展）。未执行桌面 Excel/LibreOffice 或浏览器视觉验收。

机器记录：`result.json`、`independent-readback.json`、`bridge-result.json`。本次原始 source-written.xlsx SHA256 为 `48fd01c7d7da26e214a8b4bc5102858f0ef7bd8d1c37b96786a37b64cd9c8ad6`；`probe.mts` SHA256 `53f0261dac3f8b6e942d1b3e6a4a3f564466dc0649b2a0d0257637ae579cdf50`。这些是本次临时运行身份，重放 ZIP 时间戳可能改变归档 SHA256，应按 XML 内容与保全结果核验。

## 4. 可直接实施的最小方案（未实施）

交付范围：当前活动表选择至少两列，每行一个迷你图，宿主在右侧一列，三类新增；支持 Undo/Redo、草稿恢复、真实保存下载、显式新修订重开。已有原生 groups 不变；不顺带扩展编辑／删除原生组、跨表新增、任意定位对话框、AI 候选。

建议公共协议（命名为建议，当前 bridge 不接受）：

```json
{
  "kind": "appendSheetSparklines",
  "sheetName": "Sheet1",
  "groups": [{
    "type": "line",
    "cells": [{"cell": "E2", "sourceRef": "Sheet1!$B$2:$D$2"}]
  }]
}
```

单次操作新增1–200宿主（使用明确上限），类型限定 `line|column|stacked`，可选 `color:#RRGGBB`；cell canonical 单格，sourceRef 必须解析为当前表合法范围，宽至少2、每条单行；完整 batch 先验证 grid 上限、重复宿主、文件原有占用与可可靠读取的扩展结构，再返回新 bytes。不要把跨表/不支持语法拼进任意公式。原工作簿期望 SHA256 与现有授权保存链继续负责文件身份。

最小改动落点：

1. `X/packages/xlsx-engine/src/sparkline-additions.ts`（新）+ `src/index.ts`：迁移固定源纯 `applySparklineAdditions` 的追加逻辑；包装本地 `createBufferEntrySource/resolveWorksheetPath/assemblePackage`，保留已有 raw groups 和其它 ext。复用地址解析、XML escape、ZIP 包装，不引入新 ZIP 或绘图库。宿主冲突检测补 namespace-aware 读取或对未知形态明确拒绝，不照搬源 literal-only 检测当完整保护。
2. `X/bridge/operations.ts`：strict schema + 新 case；不调用全表替换 `applySparklines`。`native_office.py::_XLSX_FIELDS` 加相同顶层字段，以覆盖独立原生 XLSX 保存；当前 `WorkbookOperation` 是通用 record，不需要新建另一套草稿存储。报告既有保存路径继续调用共享 bridge。
3. `F/workbook-sparklines.ts`（新）：最小选择→添加计划与 journal helper；按稳定 sheetId 保存会话 entry，收集时解析最终表名和绝对引用，删除页则移除该页待新增，改名须同步引用；重放仅一次，不能同时保留 staged operation 和重复收集的 journal。拒绝超200行与最右列，明确错误原因。
4. `F/workbook-main.ts`：接 `sparkline` handler、当前 dirty 状态、`currentOperations/loadOperations`、Undo/Redo 与画布 `setSparklines` 刷新；目标随 sheet 身份绑定，异步操作返回后重新核验身份。为未保存 additions 增加结构移位保护，避免保存前插删行列导致源/宿主漂移；不要通过永久禁用全部结构命令糊住问题。
5. `F/workbook-ribbon.ts`：三 action 传可执行 command，删除这三项过期 disabled reason。不以取消 disabled 代替以上接线。

必须注意操作顺序：本地 collector 已重建 sheet plan 和结构变化；新增应按最终 sheet 身份/名称序列化。对于新增后再改名、撤销改名、删页、恢复草稿，要验证既有源引用与 session entry 不会指错页。新增后源/宿主行列编辑要么完整同步（超本最小范围），要么在 UI 与 bridge 一致明确拒绝并保持原字节。源本身的结构边界不是允许静默错位的理由。

## 5. 关闭本缺口所需验收

以下是实现后的定向验收清单，本轮没有将其记成已完成：

- 三类型真实字节保存，带空格／单引号／中文表名，下载 ZIP 独立回读原始公式与宿主；普通数值/公式编辑后曲线刷新；显式新修订重开后显示正确。
- 已有原生组（自定义颜色/负色/未知属性/分组）追加后原 block 保持，foreign ext 保持且扩展都在根 extLst 内；不同颜色不会归并污染。
- 重复宿主、跨 batch 重复、越界、单列、201行、未知扩展形式、晚到无效组要有确定失败行为；不留下部分输出或清空已有对象。
- 真实浏览器创建→Undo→Redo→未离焦保存→草稿恢复→新修订下载重开；切表、改名、删页、旧会话迟到操作不串页；保存 payload 不重复追加。
- 已有原生组与 session additions 的结构保护；已有跨表引用不误画成当前表；不以 openpyxl 无对象支持当作迷你图功能证据。
- 不构建或验收无关共享功能。若实施触及报告发布链，继续遵守 AGENTS.md 非阻断下载契约；本方案优先复用原链，不新造发布门禁。

本调查提供了源实际写入与独立回读、可复用点、实测风险、协议和文件落点；**没有把调查、源函数实验或按钮标签算作本地功能交付**。


## 6. 调查后实施的两处独立 writer 修复

root 完成构建并授权后，仅修改 `smart_reporting/reporting/workbook_engine/packages/xlsx-engine/src/sparklines.ts`，新增 `packages/xlsx-engine/tests/sparklines-regression.test.ts`。这不是第4节的新增闭环实施；没有修改桥、main、Ribbon、Python 许可或 AI schema。

实际改动：

- 新迷你图写入已存在的根 `extLst` 时，在 `</extLst>` 前插入，保留其它 ext 原文；空 `<extLst/>` 复用为单一根列表；匹配根列表的 worksheet 尾部，避免选中单元格自己的列表。
- 写出分组除 kind 外还区分规范化颜色、折线 markers、showAxis，使同类型异色、不同 markers/axis 不互相污染；移除因修改失去用途的 `spec_axis`。

TDD 证据：新测试初次运行4个向量均按目标症状失败（非空 extLst 新 ext 位于外部；空列表出现两个列表；line 颜色/markers/axis 泄漏；column axis 泄漏）。修复后仅运行原 `sparklines.test.ts` 与新 `sparklines-regression.test.ts`，**2文件、7测试全部通过**；随后 `tsc --noEmit -p packages/xlsx-engine/tsconfig.json` exit0。未运行完整测试，未 build dist。实际工具输出的事后记录（未重跑测试）：`/tmp/xlsx-sparkline-gap/red.log`、`/tmp/xlsx-sparkline-gap/green-tsc.log`；日志明确标记为原工具输出摘录，非原始重定向全量日志。

修复后独立重新写出的探针保存在 `/tmp/xlsx-sparkline-gap/fixed/`，原 `/tmp/xlsx-sparkline-gap/` 的失败脚本、JSON、XLSX 没有覆盖。fixed `probe.mts` 与 `readback.py` 按修复后的期望重新执行，机器记录 `result.json`、`independent-readback.json`：

- `local-written.xlsx` 独立 XML 颜色分别为 `FFFF0000`、`FF00FF00`。
- `local-foreign-extension.xlsx` 合法根 `extLst/ext` 下有1个迷你图组，`misplaced_root_ext_count=0`，foreign 内容保留，ZIP CRC 通过，openpyxl 普通单元格可读。
- 固定源三类型写入、普通 B2 编辑后保留的向量仍通过。

修复后的同类型属性测试含3种折线属性组合及同色柱形不同 axis。属性相同可以继续共享 group，不要求一宿主一group。原 writer 的全表替换 API 语义仍保留；跨表读取身份丢失、未知原生属性保全、Ribbon 新增闭环等仍是第2–5节登记的缺口，不能因这两个缺陷修复而关闭。

`SOURCE-SHA256.json` 是原 vendor 来源清单，本轮未改写成“与上游相同”；root 可据项目清单策略另外记录本地补丁身份。本次无修改 dist，冻结构建产物不包含本节源修复，不能把同期 built 浏览器验收声称为这两处修复的验收。
