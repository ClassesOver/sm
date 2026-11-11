# Word Cell 自动换行独立调查

调查日期：2026-11-10。固定完整源码 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮只读调查；只新增本文件和 `/tmp/word-cell-wrap-investigation/` 证据，不改 production、vendor、AUDIT，不运行旧测试或产品构建。

## 结论与控件盘点

选定唯一未闭环的真实 source 功能：Table Properties → Cell → **自动换行**，即 `wrap` 复选框对所选单元格 `w:noWrap` 的编辑。不要把 `w:tcFitText`“适应文字”捆绑进来：固定 source 的 Cell 页没有该控件，TableCell model、命令和 PM 属性也没有独立 fitText 编辑能力。本轮 fixture 特意含有 `tcFitText`，仅验证原标签保留，不能据此声称其已实现。

| Cell 页全部控件 | 固定 source 路径 | 本地现状 |
| --- | --- | --- |
| 首选宽度 | `setSelectedColumnWidth` | 已有独立列宽闭环 |
| 垂直对齐 top/center/bottom | `setCellProps({vAlign})` | 已有九宫格对齐闭环 |
| 与整表边距相同、四边边距 | `setCellProps({cellMar})` | 已有 cell margin override/reset 闭环 |
| 自动换行 | `setCellProps({noWrap: cell.wrap ? null : true})` | source parser/PM/renderer 已消费，但本地 UI、专用 intent/operation、collector/replay、bridge 严格保存未接通 |
| 适应文字 `tcFitText` | **无控件** | 原始 XML 兼容保留；不属于本次补齐范围 |

`TablePropertiesDialog.tsx:634` 起是完整 Cell 页，`:258` 读 `wrap: !cellNode.attrs.noWrap`，`:334` 仅 touched wrap 时构造上述 patch，`:353` 委托真实 `setCellProps`；中文标签在 `i18n/ribbon/zh.ts:907`。Cell 页没有 prev/next 按钮，Row/Column 页的导航不能视为 Cell 页已有能力。

本地 `frontend/src/docx-tables.ts` 没有 noWrap 控件；`docx-operations.ts:532` 后仅允许单元格文字变化，没有专用意图时属性差异遭拒绝；bridge `edit-docx.ts` 和 Python operation whitelist 无 noWrap 操作。用提供完整可编辑 cell anchor 的额外真实 collector 探针确认报“暂不支持修改单元格结构或样式”，不是仅凭缺少 anchor 得到的假拒绝。

## 真实命令、选择与保存

证据目录包含 `probe.ts`、`build.mjs`、`results.jsonl`、12 个 source DOCX 和72个结果 DOCX。脚本直接导入固定 source 的 `setCellProps`、`tableModelToPmNode`、`pmDocToSavePlan`、`parseDocx/saveDocx`，不是复制命令实现。Schema 保留 source converter 实际输出的 attrs/marks；以真实 PM TextSelection/CellSelection/NodeSelection 驱动命令，无浏览器 DOM。

运行：`node /tmp/word-cell-wrap-investigation/build.mjs`，再 `node /tmp/word-cell-wrap-investigation/probe.mjs > /tmp/word-cell-wrap-investigation/results.jsonl`。这是临时探针 bundle，不是产品构建。

12 模式为 absent、true、paired、false0、false、off、rtl、merged、style、conditional、rowex、fixed。每种 caret、lower logical slot、2×2 range、bare table node 四种选择，各执行 wrap=true/false，合计96次尝试：72接受并真实保存重开，24个裸 NodeSelection 被 source `isInTable` 拒绝。`table-ops.ts:688` 的 selectedCells 通过 TableMap 对逻辑矩形去重 owner，再由 `:734` 给选中 owner 写 patch 和 `tcPrEdited:true`。没有使用或推广裸表 NodeSelection 能改全表的假设；未来 host 如需支持，必须先显式进入表内并复用既有选择协议。

- 无 noWrap → 关闭自动换行：选中 owner PM noWrap=true，保存为 `<w:noWrap/>`，重开仍 true。
- true/paired → 开启自动换行：owner PM noWrap=null，保存删直属 noWrap，重开 null；原 `<w:noWrap></w:noWrap>` 可正确删除。
- `w:val="0"`、`"false"`（paired）和 `"off"`：baseline model/PM 均无 noWrap；关闭换行写 canonical true，开启换行移除标签。source `xml-utils.ts:80` boolProp 还把 `none` 当 false，大小写不敏感；本轮未逐一命令探测其它拼写，不能将宽松 parser 行为直接当新严格协议。
- range 选全2×2时每个 distinct owner 更新。lower 在普通表命中第二行首格；merged 下 lower 与 caret 均定位同一个跨2行 owner，选区 rect top0/bottom2/left0/right1；物理 continuation 不存在独立 PM node。
- RTL 仍以源逻辑 TableMap 列操作，未翻转 left/right，也不借用段落 bidi alignment 规则。切换 noWrap 不改变 bidi、textDirection 或段落 jc 的业务意图。
- fixed 模式属性读写照常成功；视觉例外见下节。

主 probe 内本地 collector 使用只读锚点，72次拒绝为“只读单元格不能修改”。独立 `collector.ts`/`collector.jsonl` 提供 `editable:true` 的完整2×2 cell anchors 后，仍拒绝“暂不支持修改单元格结构或样式”，证明缺口是严格属性闭环本身。

## PM、生成器与 source renderer

- `convert.ts:1397` 读 `noWrap: cell.noWrap ?? null`；`:1544` 将 noWrap 和 tcPrEdited 纳入 tableStructureSignature。
- `convert.ts:1770` 起只在 tcPrEdited 或新表时把 `noWrap: !!attrs.noWrap` 交给 saved model。仅改 PM noWrap 而不走真实命令的 tcPrEdited，不能声称保存支持。
- `generate.ts:2507` 通过 `setTcPrChild` 写/删直属 noWrap；`:2375` 的 XML child 列表替换同时支持 paired/selfclosing，按 TCPR_ORDER 插入。该路径也会写 textDirection/cellMar，因此本地专用功能不应开放通用 tcPrEdited 权限。
- `extensions.ts:2756` 的 cell 样式为 `white-space:var(--doc-cell-nowrap,nowrap)`；`:3098` 对 `tblFixedLayout===true` 或 `tblOverWide===true` 的表写 `--doc-cell-nowrap:normal`；`styles.css:6513` 对 nested table 重置变量，避免继承外表的 fixed 决策。

`renderer.ts` 实际调用固定 source `DocTable.config.renderHTML`、`DocTableCell.config.renderHTML`，结果保存在 `renderer.jsonl`：true/RTL 表 cell 带上述白空格样式；false0 不带；fixed 表即使 noWrap=true 也带 table variable normal。另有明确标为 `overwide-synthetic-render-only` 的属性注入，仅证明 renderer 分支，不冒充真实文档布局探针。未运行浏览器像素/分页或 Microsoft Word/LibreOffice 视觉验收。

因此 UI 可保存“自动换行”属性，但不得承诺 noWrap=true 始终肉眼不换行；固定布局/受限宽度仍可换行，不应以视觉强制放宽列宽、改 AutoFit、缩小字体或改 tcFitText。

## 继承边界与合并保真

`parse.ts:6190` 只通过直属 tcPr 的 boolProp 读取 noWrap。真实 style 模式的 table-style `tcPr/noWrap`、conditional firstRow `tcPr/noWrap` 均没有投影到 model/PM；rowex 模式额外放入 `tblPrEx/noWrap` 仅作 parser 忽略边界探针，该位置不是标准 noWrap 定义，不能称为有效 Word 继承。style/conditional 实验只证明固定 parser 的范围，不证明完整 Word 样式级联。未来 protocol 应说明采用当前 source 直属属性语义；若需要宣称 Word 完整继承，须另立范围并验证合法 styles/default/conditional 链，不能默默发明 effective 值。

merged fixture 的 A1 vMerge restart、A2 continue；A1 noWrap=true，A2 显式false，A2含独立“hidden”正文、tcFitText/textDirection/unknown sibling。source owner noWrap切换会改变 signature，`convert.ts:1650` 清 continuationCells；因此重生成 A2 从 owner 取 noWrap，开关同时影响 owner/continue，但 **A2 hidden 正文丢失**。普通段落 rsid丢失、grid2001/1999重写成1995/1995、段落 end规范化也被观察到。即使设置当前相同状态，tcPrEdited本身也可能触发重生成。不能把这些副作用复制成本地功能契约。

`verify.py` 已核验全部72 source结果：四个 tcFitText均保留，unknown tcPr sibling仍4个；除document.xml/core.xml外所有实际 ZIP部件原字节，样例实际只有document.xml变化。细节在 `zip-xml-verification.json`。merged caret结果 hidden=false；该副作用真实存在。

另生成两份 **parser-reference-only** merged wrap/nowrap DOCX，仅 surgical 替换/删除直属 noWrap，并保持其余 XML和所有非document ZIP部件原字节；`reference.ts` 实际 parse+convert，`reference.jsonl` 确认 owner/continue flags正确、hidden=true，PM owner rowspan2保留。这证明目标补丁可行，不冒充 source UI/命令保存能力。

## 后续最小协议与无损补丁建议（尚未实现）

建议独立 `setTableCellWrap`，外层仅 `kind,blockId,expectedObjectSha256,steps`。每步严格 `top,left,bottom,right,wrap:boolean`，logical half-open rect，有限整数、界内、非空，step上限50；不接受 noWrap/raw XML/PM payload/tcPrEdited/physical映射/style/effective参数。用正向 wrap 消除 UI 双重否定；适应文字仍无入口。

capability 签发 owner logical rect、当前 source noWrap boolean和必要的物理 owner/continue直属 raw noWrap身份（raw仅服务端权威/签发快照，不让客户端决定映射）。PM投影按 TableMap去重 owner，wrap=true投影null，false投影true；只改 noWrap 与专用 native intent，不改通用 tcPrEdited、rawTcPr、continuationCells、宽度、段落或字体。重复操作累积steps，并严格按来源快照回放；collector/replay验证最终投影完全相等，其他属性/正文变化拒绝，同表其它编辑不混用。用户选当前同值可直接跳过，不因tcPrEdited产生假变化。

bridge先对原快照整批完成字段、hash、保护、几何、合并和安全边界校验。把选中的每个 logical owner映射到其全部 physical owner/continue，只写/删其 direct tcPr/noWrap；wrap=true删除，false canonical `<w:noWrap/>`。这保留source命令对合并逻辑格生效的语义，同时避免重建隐藏正文。必须正确处理paired/valfalse、缺tcPr、自闭合tcPr、tcPr schema顺序（noWrap在shd后、tcMar/textDirection/tcFitText/vAlign前），保留所有非目标bytes；不改tcFitText，不清continue正文，不调用table再生成。

首版 capability 对 namespace遮蔽、重复/含非法属性或子节点的noWrap、歧义值、属性修订、畸形grid/merge、gridGap/hMerge及超限表给独立只读原因。合法常用on/off值应由明确严格解析表支持并验证；不把source任意未知字符串视true的宽松行为搬入安全协议。未知无关siblings原样保存，不能仅因不理解无关tcFitText就误改或删除它。继承边界若无法可信界定，应明确只读原因或限定直属属性语义，不能伪造Word继承结果。

保存用独立XML save block，操作预校验失败不写输出；回读按finalBlocks实际索引定位多表，核对raw目标XML、owner/noWrap状态、合并continuation及非目标身份。仅此操作须保留docProps/core及其它ZIP部件。整表浮动、RTL、fixed/AutoFit等显示状态不能成为顺手改宽度/定位的理由。

验收至少包括：真实source caret/range/merged lower语义；无标签/paired/true/false开关；只选一格不外溢；PM/collector/replay恶意扩权拒绝；unknown及tcFitText保真；hidden continuation原样；fixed/overwide视觉解释；style边界；protected/hash/same-table冲突；多表逆序加段落增删及迟到无效step无输出；保存后实际重开和非目标ZIP bytes验证。不要复跑已有完整测试；落地时只跑新增窄回归与受影响集成。
