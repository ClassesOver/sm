# Word 清除所有格式：当前闭环与边界

日期：2026-11-09。对齐固定源 `f8c17004fb730df11f0f743164ffd8b4281bb38c` 的
`apps/docs/src/renderer/components/ribbon-tabs.tsx`：`clearAllFormatting`、
`applyParagraphStyleId`、`shedMajorityDirectFormatting`、`DIRECT_PARA_ATTRS`。

## 已实现

- 开始页清除格式按钮接通；选中文字去除全部 marks（含链接）；折叠光标清除整段字符格式。
- 触及的段落恢复来源文档的默认段落样式，标题转普通段落；列表保留编号及级别，
  原样式继承的编号在文件中具体化，避免恢复 Normal 后丢失。
- 按源规则清除直接段落属性；应用样式时，选区清除后仍覆盖超过半段的
  B/I/U/strike、颜色、字号、font/fontAscii 整段移除；恰好一半保留。
- 使用原子 `clearParagraphFormatting` 操作及隐藏意图记录有序范围；正文投影必须
  与来源确定性投影完全相等。来源 block/hash、UTF-16 边界、范围数量、草稿回放及
  同段互斥校验均覆盖；客户端不传任意样式 XML。
- 多段、全选、连续清除、空段、撤销重做及草稿恢复已有定向测试。非目标 XML 属性
  与 ZIP 部件保留；选区外少数字体槽保留。

## 验证

- 前端新增 `docx-clear-formatting.test.ts` 6 项通过；最终与 format-range/operations/ribbon
  组合执行共 86 项通过。
- Python `test_docx_clear_formatting.py` 10 项通过；最终与 format-range 组合共 19 项通过。
  字体槽与继承编号回归均先见失败再修复。
- 真实 Chromium 140.0.7339.16：`DOCX_INSERT_CASE=clear node smoke/docx-insert-gui-smoke.mjs`
  通过。清首段整段粗体→撤销→重做→刷新恢复草稿→真实 Python patch_docx 保存→下载
  python-docx 独立回读→修订 2 重开；其余段落粗体保留，`pageErrors=[]`。
  本次产物 `/tmp/docx-insert-gui-dC5Me4/revision-2.docx`。
- bridge bundle、定向 bridge TypeScript 校验、前端 build 与体积预算通过。
  现有 chunk-size/Radix/circular chunk/jsdom canvas/font-shadow 提示仍存在。
- 独立审查发现 ASCII 槽被连带清除、只剩东亚字体槽时生成器漏写，均已补回读回归修复。

## 尚未覆盖

- 只支持唯一来源锚点的顶层可编辑文字段、标题和列表；表格单元格、文本框子编辑器、
  页眉页脚子编辑器、含内联对象的段落、新增未保存段落仍未接通此操作。
- 同段已有文字或其他格式变更需先保存；清除后同段其他编辑也需先保存。
- GUI 本轮验证折叠光标整段场景；局部选区、标题、列表、多段依赖定向集成与文件回读测试，
  尚未逐项完成真实浏览器验收。HTTP 路由为替身，未验生产鉴权及数据库发布链。
- 不据此关闭 Word/XLSX 全量对齐目标。
