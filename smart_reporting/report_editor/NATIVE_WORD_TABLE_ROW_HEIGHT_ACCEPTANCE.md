# Word 指定及清除行高验收

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；来源与真实探针见 `NATIVE_WORD_TABLE_ROW_HEIGHT_INVESTIGATION.md`。指定/清除行高已完成本专项验收，均分行高另外待办，不代表全量对齐完成。

## 已接入行为

Ribbon 行高作用于当前逻辑行带，合法合并格 caret 覆盖完整 rowspan，整表选择覆盖所有行。空值或用户输入 0 恢复自动；协议只传正安全整数或 null。指定高度保留原 exact/atLeast 规则，无有效原高度时使用 atLeast；上限来自表格所在节正文高度。合法 auto/零声明可编辑，空或未知 hRule 拒绝。

严格 setTableRowHeights 协议绑定原对象 hash，不接受客户端上限或 XML。最多50步骤、100行/30列/1000逻辑槽；保护来源不可编辑。同表文字/格式/结构混编、同节布局/分节混编拒绝，避免错误来源依赖。collector 完整比对共享投影，草稿恢复复用同一逻辑。

bridge 只新增、更新或删除直属 trHeight，保留 trPr 空白、其他行属性、格网、复杂 continuation 隐藏内容及所有原段落 XML；实际保存重新读取并验证结果，其他部件按文件字节保留。

## 定向验证

- core3、bridge初3及追加严格几何向量通过；auto/空规则新增2项 RED→GREEN，限定类型检查通过。
- UI 最终7项通过，包括0/空值清除、逻辑选区、Undo/Redo、collector/replay、锁/混编和原节clamp；列宽兼容9项通过。
- Python 初始6项中的非法请求/节上限5项通过，保存项因新增ZIP目录条目导致断言失败；按实际OPC文件过滤目录后仅重跑保存项通过，仍严格验证段落及非目标文件字节。追加保护/hash1项及auto来源3项通过。
- 前端节依赖契约1项通过；集成类型检查 `/tmp/word-row-height-integrated-types.log` exit0。
- 最终 bridge `/tmp/word-row-height-final-bridge.log` exit0。

未重复完整项目套件。日志索引详见调查文档及 `/tmp/word-row-height-*.log`。

## 最终构建与浏览器

首轮统一前端构建通过，但 XLSX main 超出250KiB预算0.4KiB；只把独立高亮模块拆分加载，不提高预算。最终 `/tmp/office-row-height-cross-highlight-final-build.log` exit0（40.51s），同前缀 budget 与 budget-contract 均 exit0。

独立 `frontend/smoke/docx-table-row-height-built-smoke.mjs` 首轮 exit0，日志 `/tmp/word-row-height-built-smoke.log`：ok=true/errors=[]，120个加载JS身份核对；产物 `/tmp/docx-row-height-built-hEuDYT`。公开UI指定600保exact→Undo/Redo→第二行输入0清除→草稿刷新→真实Python保存/HTTP下载→修订2重开，随后750新增atLeast保存/修订3；独立复杂rowspan来源caret覆盖两行900保存/修订11，30000请求截到14800原节上限再存/修订12通过。

DOM行属性在Undo/Redo、草稿刷新与重开严格比对；掩去直属trHeight后整个document.xml逐字一致，所有其他OPC部件字节及逻辑/物理格身份保持。普通下载SHA256 `819af49c355b960c14f7578917b02693ec73d72f6f6ea91bb339ca1803155090`。root目视修订12截图，确认达到上限的行实际占据对应高度；其他正常高度重开截图另补。未将浏览器替身路由称为生产HTTP验收。

## 剩余范围

均分行高必须按来源 DOM/zoom 测量，不能以原声明高度平均替代；拖边界及其他表格属性仍需独立实现。浏览器授权/修订接口使用替身，真实 Python/文件回读不证明生产 HTTP、桌面 Word 或 PDF 排版等价。
