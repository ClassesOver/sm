# Word 指定列宽与均分列验收

固定来源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本文记录列宽专项，不代表 Word/XLSX 全量对齐；来源调查见 `NATIVE_WORD_TABLE_COLUMN_WIDTH_INVESTIGATION.md`。

## 实现与契约

- Ribbon 指定列宽、均分列共用 `docx-table-column-width-core.ts`，复用固定来源 `fitColumnWidths`。指定宽度沿用来源 twip 输入转整数像素语义；多列均分限于选区，单列均分扩为全表，合并格按逻辑跨度处理。
- `resizeTableColumns` 仅接收来源 block/hash 和最多 50 个步骤，不接受客户端节宽或任意 XML。服务端从表格所在节计算可用宽度；多栏及无法解释的几何来源只读，同表其他编辑及同节页面布局混用须先保存。
- 整数 twip 使用最大余数分配；未触发最小宽度或页面约束的均分保留原整数总宽。加载 baseline 前恢复可信来源的精确 twip/15，不产生编辑、更新事件或撤销记录，草稿从原 baseline 重放。
- bridge 只替换原 `gridCol/@w:w`、`tblW/@w:w`、`tcW/@w:w` 属性值；包括纵向合并 continuation。段落、隐藏内容、主题属性、其他 XML 空白及非目标部件保留，保存后回读校验。

## 已读取的针对性证据

- core 7 项通过；bridge 初始 5 项及几何严格性追加 2 项通过；限定类型检查通过。来源两位像素取整造成多列均分丢 1 twip 的用例已 RED→GREEN。
- UI 初始 6 项、真实宿主合并网格追加 2 项通过；原表格与合并拆分兼容 40 项通过。加载/重开奇数 twip 的归一化回归先缺 helper 失败，再单项通过，最终前端类型检查通过。
- Python 初始非法协议 4 项、合法保存 1 项、实际来源节上限及多栏/混批边界通过。合法保存测试曾使用错误的 python-docx 属性，修正为 `_p.xml` 后仅重跑失败项。
- 最终构建 `/tmp/office-word-column-width-final-build.log` exit 0（39.85s），budget 与 budget-contract 同前缀日志 exit 0，未放宽预算。bridge `/tmp/word-column-width-final-bridge.log` exit 0。

## 最终浏览器验收

`frontend/smoke/docx-table-column-width-built-smoke.mjs` 最终 `/tmp/word-column-width-built-smoke-rerun.log` exit 0，`ok=true/errors=[]`；实际产物 `/tmp/docx-column-width-built-tanTUM`。Chromium 140.0.7339.16 公开 UI 完成单列设置→Undo/Redo→单列均分全表→选两列局部均分→草稿刷新→实际 Python 保存→实际 HTTP 下载→修订 2 重开。DOM 宽度乘 15 与签发整数 twip 严格一致；独立横纵合并来源保留隐藏 continuation 内容，设置后保存下载并修订 11 重开；30000 请求受 9000 节宽约束，多栏来源明确只读。

原始/目标整份 document.xml 在仅脱敏三类宽属性值后逐字相同，其他 ZIP 部件逐项相同；加载 JS 的 SHA 与最终本地构建一致。普通下载 SHA256 `f72cbf02548384575c393def950c5393b2a94075c5bef8dfa0c03bafd7d225a8`，合并来源下载 `6b90fd7f4490183eeded7ddef4d70ee48ec5a91d6014bc7f7f87902d6498a4b2`。

首轮 `/tmp/word-column-width-built-smoke.log` 失败：脚本在 Undo 与 Redo 之间点击 Ribbon 标签夺走编辑焦点。去掉这次无关点击并增加 Undo 恢复原始奇数宽度的精确断言后重跑通过；未修改生产代码或放宽断言。下载使用随机 localhost 真实 HTTP 端点，授权与修订保存路由仍为替身。

仅快速重开现存修订补截图（没有重复编辑保存全流程）：`/tmp/word-column-width-reopen-screenshots.log` exit 0、errors=[]，DOM 宽度再次匹配 inspect。root 目视 `/tmp/docx-column-width-built-tanTUM/revision-11-column-width-reopened.png`，合并布局、中文及混合格式正常；隐藏 continuation 的保留由 XML 断言证明。

## 后续边界

行高/均分行、AutoFit 切换、拖动边界、嵌套表直接宽度编辑、复杂或未知几何来源仍需独立实现和验收。当前浏览器脚本使用替身授权/修订存储与真实 Python/ZIP，不代表生产 HTTP、桌面 Word 或 PDF 排版等价。
