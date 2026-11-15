# 原生 XLSX：表格所属关系完整性边界

日期：2026-11-11。对应上游源码固定版本：genoffice-source-full
f8c17004fb730df11f0f743164ffd8b4281bb38c。

## 范围和发现

2026-11-10 已有只读／未投影 table 的独立身份快照、live 依赖检查、共享 OPC 删除规划、journal 和文件侧兜底。本次没有重建这些机制，也没有重复其旧完整 browser 流程。

本次确认一个额外的畸形 OOXML 边界：worksheet 的 .rels 中有 First、Second 两个 table 所属关系，而 worksheet 的 tableParts 完全缺失，或仅登记 First。修复前 reader 分别发布空 tableSources 或仅包含 First 的 tableSources，却把它们当作完整来源。实际删除规划仍识别两份 table part；因此 UI 可以漏看 Second 的结构化引用，迟至保存时才被文件侧保护拒绝。

## 最小修复

- table-read.ts 在发布独立身份前，核对 worksheet 的 table 关系是否全部登记于 tableParts。存在未登记关系时，不发布部分 tableSources，并返回“表格所属关系未完整登记在工作表中”。
- 原有 assertTableSheetRemoval 消费此来源不完整原因，在读取 live table 列表或执行删除前拒绝操作。无需修改 main、ribbon、journal、HTTP API 或发布／下载链路。
- 仍不扫描 ZIP 猜测表归属。真正的 orphan 是既无 worksheet 注册、也无 incoming table 关系；这类未归属 ZIP part 保留，独立来源是完整空列表。
- 此边界只拒绝不能确定安全性的工作表删除；不把普通表格投影失败变成整个工作簿不可编辑。

## 本次文件

1. reporting/workbook_engine/packages/xlsx-engine/src/table-read.ts：关系完整性核对。
2. reporting/workbook_engine/packages/xlsx-engine/tests/table-source-owner-completeness.test.ts：all、second 两种实际 engine 字节故障夹具。
3. reporting/workbook_engine/packages/xlsx-engine/tests/table-read.test.ts：原有 orphan 夹具同步移除 incoming 关系，保持真正 orphan 语义。
4. report_editor/frontend/src/workbook-table-sheet-removal.test.ts：用实际 readWorkbook 模型证明来源不完整时，live getTableList 尚未调用即拒绝。
5. report_editor/frontend/smoke/workbook-table-owner-completeness-built-smoke.mjs：新增边界的窄 built-browser 验收入口。

上述路径相对于 smart_reporting/；本记录不代表共享工作树中的其他修改。

## RED → GREEN

新增 engine 两用例在旧 reader 上均真实失败：all 得到 []，second 得到仅 First 的身份，而断言要求来源未知。RED 输出：

    /tmp/readonly-table-owner-completeness-red-20261111.log

该次 shell 为展示日志而追加 cat，最终 shell exit code 为 0；以日志中的 Vitest 2/2 failures 为 RED 证据，不把 shell 退出码称为失败证据。

最小修复后的定向检查：

- Engine 四个文件 43/43 通过：table-source-owner-completeness、table-source、table-read、owned-table-delete-dependencies。日志：/tmp/readonly-table-owner-completeness-green-20261111.log。
- Frontend workbook-table-sheet-removal.test.ts 10/10 通过。日志：/tmp/readonly-table-owner-frontend-green-20261111.log。
- Engine npm run typecheck 通过。日志：/tmp/readonly-table-owner-engine-tsc-20261111.log。
- Frontend tsc 在共享树的 docx-comment-reply.ts、slides-hidden.test.ts 报错；不属于本次改动，未越界修改。日志：/tmp/readonly-table-owner-frontend-tsc-20261111.log。
- 新 smoke 脚本 node --check 通过；单独执行其 Python 夹具生成并用 ZIP/XML 验证，两变体分别 registration=0/1，incoming table relationships 均为 2。
- 未运行完整测试套件，未自行重建共享 dist/static。

## 实际 XLSX 与独立读取

文件及证据目录：/tmp/readonly-table-owner-proof-20261111。

valid.xlsx 用 openpyxl 生成 Source、Other 两表，Source 内有 First(A1:A3)、Second(C1:C3) 两张真实 table，Other!A1 为 =SUM(Second[Count])，Other!B1 为加粗的数值 17。故障文件只做所述 OOXML 注入，不把它们声称为 schema 有效文件。

| 变体 | 独立身份结果 | 实际规划删除 table parts | SHA-256 |
| --- | --- | --- | --- |
| readonly | 两个身份保留，editable projection 为只读 | 2 | 5ba9994895a8191ecefb3cefd7c7edefb1ca6e185428f62d64368b4a3bd6e0f6 |
| missing-all | 不发布身份，返回归属登记不完整原因 | 2 | 291d249c5580957c8aef0ab08217614c2841c70047f0f168cb0875b87eb728ff |
| missing-second | 不发布部分身份，返回同一原因 | 2 | d0c671d0de3dd9218da0576b7d7f1bb368ab5170a4f186845da32329d1cff088 |
| orphan | 完整空身份，无来源错误 | 0 | 16048c126f133ae779115eb65719095cf97d26283e2282857b5f0c8eb905e47e |

engine-evidence.json 记录实际 readWorkbook、planSheetRemovalParts 和 applySheetEdits；前三个文件的保存删除均因 Other 的 Second 引用被现有文件侧依赖保护拒绝，原始字节不变。

independent-evidence.json 使用独立 openpyxl 和 ZIP 读取核验：四个文件均仍含两份实际 table XML；openpyxl 对 missing-all、missing-second 分别只认识零张、一张已登记 table，证明仅靠 worksheet 注册会漏掉真实关系。Other worksheet XML、styles.xml 与源文件字节相同；公式和加粗 B1 保留。

## 新构建 browser 验收入口

旧 manifest e2faddb5fb62f0db91b90b3248be4b8355ab5979d0b110eaa92dfde27dfe4daa 不含本次 table-read 修复；不得用旧构建声称本新增边界已通过 browser。

由主任务统一构建 engine bundle 和 frontend 后，在 frontend 目录执行：

    WORKBOOK_EXPECTED_MANIFEST_SHA256=<统一构建清单SHA256> \
    TABLE_OWNER_EVIDENCE_DIR=/tmp/workbook-table-owner-completeness-built-20261111 \
    node smoke/workbook-table-owner-completeness-built-smoke.mjs

此脚本仅验证两个新边界：从实际 XLSX 打开，右键 Source → 删除 → 确定；出现来源登记不完整的具体原因，Source/Other 同时保留，localStorage 草稿与 save label 不变，mutationRequests=[]、pageErrors=[]。记录 actual manifest SHA、HTTP 200 runtime JS 与磁盘文件逐份 SHA 匹配、真实 XLSX 和截图。

截至本记录编写，脚本准备完成，但尚未在包含修复的新统一构建执行。既有完整只读删除、Undo/Redo、草稿恢复和保存证据仍属于前次验证；本次不重复、不冒充新验证。

未声称生产部署、provider、鉴权或真实用户环境验收。


## 8c3 冻结构建的新增完整性窄验收

root 实际执行 /tmp/workbook-table-owner-completeness-built-20261111/evidence.json，进程exit0、ok=true。manifest为8c3baa3ed28283fb6e443e22b4590ee3ab82c38fd1f592a0bbcb06076c300a9c。

- 两个真实XLSX来源：漏登记全部tablePart、只漏第二张。通过官方工作表右键→删除→确认实际进入主视图保护，均明确显示“表格来源无法完整核对：表格所属关系未完整登记在工作表中”。
- 每个场景127个实际JavaScript响应SHA与磁盘字节一致；pageErrors=[]，mutationRequests=[]。Source与Other两个工作表均保留，localStorage草稿与保存状态标签均原样。
- root 独立实读证据并目视owner-second-refused.png；本轮只补新完整性边界，不重跑11月10日已有只读表删除/UndoRedo/保存整链。截图中的中文原因可见，源表与依赖表均保留。
- 冻结构建随后若仅Word提示变动，资源连续性必须另证；不把本条8c3结果改称新版本重跑。
