# 条件格式规则编辑：源能力与完整链差异

固定源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮仅调查，不修改 shared main/ribbon/engine，不提前开放无法保存的管理器。

## 源行为

- `ribbon-actions.ts:476` 执行官方 `sheet.operation.open.conditional.formatting.panel`，参数必须 `{value:2}`（管理规则列表）。`App.tsx:2196/2234` 注册官方 CF preset、locale、CSS。
- `univer-sync.ts:6385` 对每个 cfDirty sheet 读取 `getConditionalFormattingRules()` 全集，连同 ranges、stopIfTrue、rule JSON 交 gateway。不是逐条 append；删除到空集合也是一次有效保存。
- 固定 gateway `xlsx-cf.ts` 默认全规则替换；只在显式 append 参数下追加。顺序对应 priority；保留 x14-linked 原块，不能简单删光 XML；无对应表示或编辑受保护扩展时明确拒绝对应编辑。
- 源可保存四大类：highlightCell、dataBar、colorScale、iconSet。highlight 含 number、text（contains/notContains/begins/ends/equal/notEqual/blank/error）、duplicate/unique、rank（前后 N/百分比）、average（gt/gte/lt/lte）、formula。date-occurring/timePeriod、average equal/notEqual 等源序列化不支持，源执行前使用同一 serializer dry-run 拦截，不能把它们纳入“源已支持”。iconSet 仅标准 OOXML 图标集，且同一set内顺序或反序的完整iconId序列。
- dxf 样式源支持 bold/italic/strike/underline、文字和填充 RGB。源serializer也处理 RGB/rgba 字符串转换。

## 当前本地差异

1. package已安装官方CF preset，但 workbook-main 未导入注册，locale和CSS也未接。sync loader 以可选 facade add 调用读取模型，不能证明真实引擎中已渲染。
2. `cf-read.ts` 明确只读 dataBar/colorScale；cellIs 的 dxf 与 iconSet 均 write-only。text/duplicate/rank/average/formula更无完整读取投影。panel若只看当前读取模型会遗漏原规则，之后替换会损坏文件。
3. 当前 `applyCfRules`（`rules.ts:343`）是包级追加 API；空数组直接返回原文件，不支持管理器的改/删/重排。原调用者可能依赖append，不能直接改变其默认契约。
4. 无原生CF command dirty监听、草稿全规则快照、全规则替换操作、replay、差分及保存重开投影。已有 `applyCfRules` protocol 只能证明部分headless新增。
5. 当前 `engineCfToUniverRule` 只转两个可读类型。源 dataBar serializer 自身明确只存 positiveColor，负色属于 x14 而丢弃，不能误列为“源已完整保存、本地独缺”。源 colorScale 接受至少两站点并按 index 排序，本地schema限定2–3站点；需要对官方panel实际可创建范围继续验收，不能凭单个schema称全量一致。

| 源可保存域 | 本地writer | 本地reader/原生管理链缺口 |
| --- | --- | --- |
| number highlight（8种cellIs比较） | 有cellIs写入和有限dxf | 没有cellIs/dxf读取，不可编辑已有规则 |
| text contains/notContains/begins/ends/equal/notEqual/blank/error | 无对应wire序列化 | 没有读取/Univer双向映射 |
| duplicate/unique | 无 | 没有读取/双向映射 |
| rank（前后N/百分比） | 无 | 没有读取/双向映射 |
| average gt/gte/lt/lte | 无 | 没有读取/双向映射 |
| expression/formula | 无 | 没有读取/双向映射 |
| colorScale | 有2–3站点写入 | 有基础读取；缺管理器增改删/顺序/草稿/全替换 |
| dataBar | 有单正色及阈值/showValue | 有基础读取；缺管理器全链，需核源阈值映射 |
| 标准 iconSet | 有标准set、阈值、reverse/showValue写入 | reader缺失；缺官方best-first/文件ascending转换、4Rating/5Rating特例 |
| x14-linked基础规则/未知CF | append原字节保留已有块 | 无完整身份/保护性读取；replacement必须防静默丢弃，保留原priority及扩展 |

所有以上源可保存而本地缺失的域都仍是全量对齐缺口；不能通过将它们永久设成“复杂来源只读”而计完成。临时保护只为避免损坏文件，最终仍须实现可表达的源行为。未知的非源可表达规则也应保留身份和明确不可编辑原因，不悄悄从快照中消失。

## 实际 RED

真实引擎创建dataBar后，再以颜色修改后的同范围调用现有writer，reader返回两条旧/新规则：`#112233`、`#445566`，不是一条。日志 `/tmp/workbook-cf-replace-investigation-red.log`。

另一个真实探针：`applyCfRules(first,[])` 返回同一文件bytes、仍有一条规则；cellIs写入后reader结果为零条。日志 `/tmp/workbook-cf-clear-reader-investigation-red.log`。持久化探针 `docs/parity/probes/cf-manager-save-red.mjs` 记录这一API适用边界，不要求把旧append API改为replacement。

## 最小对齐设计

优先选择性复用固定源 `xlsx-cf.ts` 的wire serializer/规则dry-run/全替换及linked-block策略，保留来源归属；适配已有StylesheetEditor dxf sink。不重新手造另一套条件规则解释器。保留旧applyCfRules追加契约，新增明确按sheet全量替换操作（即使rules=[]也写回删除），不新增一堆单规则命令协议。

必须先补读取全集（ranges、顺序、stopIfTrue、dxf格式、标准icon映射、源支持highlight类型、未知和linked扩展身份），再接官方preset和管理面板。受支持规则用官方facade载入；不能表示的来源保留原XML及只读原因，禁止静默漏掉或伪称可编辑。随后按官方增改删/重排mutations抓取真实全集，NativeDraft/replay→Python协议→全替换→ZIP/读回→reopen；执行前dry-run保证不让panel产生保存时才发现不可表示的规则。现有报告非阻断发布契约不变。

验收应含：源各类型代表、删除到空、修改不重复、优先级/stopIfTrue、undo/redo、草稿恢复、跨sheet/保护/身份、未知扩展原字节保持、错误类型不误写、真实官方panel及最终built GUI。不用仅“面板能打开”宣称规则编辑已完成。

## 独立模块实施进展（尚未接主入口）

新增 `conditional-formatting-source.ts` 为 fixed gateway/xlsx-cf.ts 逐字拷贝（SHA `db38a4ca48933595db8019acce5f45b27f1fdff2f01d43bd6ae7abd84b16e18e`），无import依赖；`conditional-formatting-read.ts` 为明确标识的本地Rust字段/renderer映射适配；`conditional-formatting-snapshot.ts` 使用现有package、stylesheet dxf sink与关系解析。来源说明见 `reporting/workbook_engine/CONDITIONAL_FORMATTING_SOURCE.md`。

`replaceConditionalFormattingSnapshots(bytes,[{sheetName,rules}])` 新增按sheet全快照替换，不更改旧append API。source sourceXml完整保留；原规则必须通过范围、优先级、dxf关联以及source重序列化全部属性/formula身份检查，未知规则或扩展不得被部分投影覆盖。替换后再次核完整读回。

实证 `/tmp/cf-snapshot-red.log` 捕获新API为noop时失败；新文件35项按变更范围分段验证：`/tmp/cf-snapshot-final-targeted.log` 34项通过，`/tmp/cf-snapshot-negative-fill.log` 第35项核源默认负数据条红色通过。覆盖源所有highlight子类型代表、dataBar、三色标/formula阈值、3Arrows/4Rating/5Rating与reverse顺序、create/replace/clear、优先级排序、dxf去重、跨sheet原字节、unknown/x14/范围/priority/dxf失配、schema默认布尔及solid foreground兼容。engine定向typecheck日志 `/tmp/cf-snapshot-types-final.log` 无错误。

明确剩余：linked-x14不变来源规则同时编辑其他规则的保真路径；无styles.xml来源的最小必要新增；更多外部等价OOXML表示（如合法主题色dxf/原生公式cellIs）读取与映射；官方preset/面板、dirty/草稿协议、最终GUI。保护性拒用不是全量完成，这些仍是源支持域的待补缺口。

### 后续 linked-x14 与缺样式表实施

上述前两项继续推进，未停在保守只读域。真实ZIP RED `/tmp/cf-linked-missingstyles-red.log` 抓到linked来源被拒绝、无styles包读取失败。现复用源完整替换策略保留唯一配对的linked基础块与sheet扩展逐字不变，保留原priority，同次允许编辑普通规则；删除或修改linked本体仍按源拒绝。reader验证base id与twin id唯一、ranges/type/priority匹配、标准x14/xm命名空间；返回linkedRuleIds/linkedRules供未来UI守卫。源negativeFillColor/gradient得到读取投影；新增本地full-wire语义身份核验，避免x14-only属性被base serializer忽略而静默no-op。

无styles.xml时复用现有rules.ts按需模板/CT/relationship新增方式；只存dataBar不创建styles，首次highlight dxf才新增必要部件，foreign styles关系不得被自动改指向。定向结果：`/tmp/cf-linked-missingstyles-green.log`（无styles项）、`/tmp/cf-linked-identity-green.log`（linked项）、`/tmp/cf-linked-foreign-boundaries.log`（7项身份负例）、`/tmp/cf-linked-render-attributes.log`（视觉属性读取）、`/tmp/cf-linked-immutable-visual.log`（修改拒绝及普通规则同存）。最终新文件46项复验日志 `/tmp/cf-snapshot-linked-final-targeted.log`；engine typecheck日志 `/tmp/cf-linked-types-final.log`。当前仍未接共享UI/协议，主题dxf及更多外部等价表示仍列为后续实现，不永久缩域。

### 正式 engine/bridge 入口

`readWorkbook` 新增 `sheet.conditionalFormatting`，包含 `rules/linkedRuleIds/linkedRules/issues`，不回传整个来源 XML；旧 `conditionalFormats` 渲染投影保留兼容。`index.ts` 导出reader/snapshot/schema以及 `ConditionalFormattingWireRule` 别名，避免与旧 `CfWireRule` 类型冲突。新bridge operation为 `replaceSheetConditionalFormats {sheetName,rules}`；严格字段/区域/stopIfTrue验证，规则可表示性由fixed source serializer dry-run决定。旧 `applyCfRules` 仍为append。

真实bridge首个RED `/tmp/cf-bridge-red.log` 为未注册新operation；8项主链GREEN `/tmp/cf-bridge-green.log`，另4项linked保源/伪造操作/越界身份GREEN `/tmp/cf-bridge-linked-boundaries.log`。覆盖真实ZIP→bridge写入/改规则不重复/清空→readWorkbook全集，未知源规则暴露issues并拒绝破坏性替换；linked删除拒绝而输入bytes保持。Python入口白名单与真实native测试由root协调。

必需typecheck曾暴露旧outline bridge的exactOptionalPropertyTypes错误，按root授权将传参规范化为仅存在字段，保留显式false，未放宽schema或强制断言。新增 `bridge/outline.test.ts` 验证真实文件中summaryBelow=false、hidden=true→false与未指定状态保留，日志 `/tmp/cf-bridge-outline-green.log`；最终两层 `npm run typecheck` 日志 `/tmp/cf-bridge-types-final.log`。

新发现后续缺口：snapshot writer可处理无styles包，但既有 `readWorkbook` 仍强制读 `xl/styles.xml`，因此无styles来源/纯bar产物的native inspect仍需按缺省样式只读投影修复。本批生产freeze后不抢改，未据writer测试称整个无styles编辑链已完整通过。

### 外部来源 ARGB、主题 dxf 与 cellIs 公式调查（生产freeze期间只读）

root真实Python/openpyxl新用例失败（`/tmp/workbook-cf-native-green-first.log`）：`DataBarRule(color='112233')` 合法写为 `rgb="00112233"`。openpyxl `styles.colors.RGB` descriptor源码明确未给alpha时前加00。固定源Rust `visuals/colors.rs:260 resolve_color` 对所有8位rgb去前2位，worksheet.rs:828/843/882的CF颜色读取调用它；固定源TS `xlsx-style-read.ts` 同样按8位slice(2)，旧本地cf-read也如此。新的完整reader只接受FF前缀是过严限制，不是文件故障，不得改fixture绕过。

独立只读探针 `/tmp/cf-openpyxl-alpha-investigation-red.log` 已复现：00前缀dataBar应投影#112233，当前报not representable。最小修复应接受任意合法8位ARGB，并仅在颜色rgb属性的同义身份归一化中规范为FF+后6位，以匹配源显示/serializer语义；只放宽color函数仍会被roundtrip身份检查拒绝。bar、scale、dxf以及00/FF/中间alpha都需覆盖，其他未知属性不得归一化掉。当前生产未修改。

失败测试已落 `conditional-formatting-snapshot.test.ts`：00/80/FF三组包含bar、scale与dxf，当前00/80失败、FF通过（`/tmp/cf-argb-cases-red.log`），未修改Python真实失败fixture。缺样式表读态也有真实ZIP失败探针 `/tmp/cf-no-styles-reader-investigation-red.log`；fixed Rust `visuals/styles.rs:13` 缺styles返回单个 `CellStyle::default()` 和空dxf，而本地仍强制read。下一阶段应只提供缺省读取投影，不能凭此无条件写新样式部件，也不能把不存在的dxf关联当可读。

此后生产窗口已实现两项源同语义修复：所有合法6/8位RGB/ARGB均取最后6位；canonical只在color/fgColor/bgColor的合法rgb属性做alpha归一化，未知属性和错误颜色仍拒用。无styles的public reader以一个空font/fill/border与默认xf的仅读投影加载，没有凭空指定font/size/color，不改输入ZIP；缺dxf引用仍issues并拒绝覆盖。`/tmp/cf-argb-no-styles-green.log` 4项通过；`/tmp/cf-argb-no-styles-edge-green.log` 2项（无font/源bytes/缺dxf及恶意颜色边界）通过；`/tmp/cf-argb-no-styles-types.log` 两层typecheck通过。root继续原Python openpyxl fixture验收，不通过改fixture逃避问题。

主题dxf：固定源Rust `resolve_color` 优先theme over rgb cache，再按theme+tint解析；现有本地style-color.ts已有resolveStyleColor/applyTint与themePalette，可复用而非新造色彩算法。保真保存仍须记住原dxf身份：单纯转RGB后重建会失去theme引用；应在未修改样式时复用原dxf，真正编辑时再按源写RGB的语义处理。主题dxf不应永久只读。

cellIs非数值：固定renderer `buildCellIsNonNumeric` 将单元格引用/表达式转换成比较公式，避免Number转换失败；数值规则也在<=20,000格且Excel空白=0与Univer跳空白不一致时转公式。引用/表达式要保留括号优先级，quoted文本需转义wildcards，避免大小写/通配符行为漂移。可选择性复用这些源纯函数，不可直接把非数值Number()失败当永久不可编辑。原始cellIs→渲染公式后的保存应保留来源身份或按源显式转换契约，避免假称逐字roundtrip；该设计仍待下一阶段验证。

## Theme/indexed/tint stage evidence

Source color resolver adaptation and original dxf identity preservation are implemented. Targeted CF tests: `/tmp/cf-theme-affected-final.log` (14 pass), `/tmp/cf-system-indexed-green.log` (2 pass), shared table regressions `/tmp/cf-shared-color-table-regression.log` (6 pass). Engine plus bridge strict typecheck after closure-narrowing fix: `/tmp/cf-theme-types-restored-fixed2.log` (exit 0). The cellIs reference fixture remains a real known RED for the next stage; these results do not claim the whole 61-test file is green.

## Linked CF structural scope repair

Linked CF structural scope repair (local deviation from fixed source): fixed
xlsx-structure.ts:1562 shifts only the base conditionalFormatting sqref. The
local structural.ts now verifies a unique x14:id/twin id, identical source
sqref/type/priority, and standard x14/xm namespaces before moving that twin's
xm:sqref. Deleting the whole scope removes both base and twin, the empty known
CF container/extension, and an empty extLst; unrelated extensions remain raw.
Ambiguous linked identities refuse only the structural edit. Multiple rules
sharing a base scope keep their original conditions. No wire fields changed.
Eight new cases first failed against the prior implementation, then passed,
including actual ZIP insert/remove/read-back and byte-identical unrelated sheet.
Two additional empty-wrapper/mixed-base cases and three existing ranged-feature
regressions pass. Evidence: /tmp/cf-linked-structure-red.log,
/tmp/cf-linked-structure-first-green.log, /tmp/cf-linked-structure-extra.log,
/tmp/cf-linked-structure-regression.log. Engine and bridge typecheck exit 0 in
/tmp/cf-linked-structure-types.log. CellIs reference parity remains a known RED;
its incomplete next-stage implementation is parked outside the repository.

## CellIs source projection and persisted identity

CellIs reference/text/blank projection (local fixed-renderer adaptation):
conditional-formatting-read.ts now follows univer-sync.ts:7481
cellIsBlankDiverges, :7517 buildCellIsFormula and :7689
buildCellIsNonNumeric. Native number comparisons remain native unless blank
behavior differs within the source 20,000-covered-cell formula budget.
Nonnumeric comparisons retain operand parentheses; quoted equality uses the
source wildcard escape and case-insensitive formula, with the same huge-range
native-text fallback. Disjoint ranges use the source top-left-sorted anchor
and summed coverage. Unsupported arity/operator/mixed numeric-between cases
remain explicit incomplete snapshots. Wire formulas omit '=', as existing
expression wire does; frontend formulaShape already adds it for Univer.

The raw cellIs XML is first verified against the fixed source serializer's
number-rule shape with exact original formulas restored for identity checking.
Only after that check is the source renderer projection applied. Persistence
recomputes matching condition/ranges from the actual ZIP, retains raw cellIs
condition XML on unchanged or style-only edits, and writes expression only
when the condition changes. Unchanged whole snapshots retain original ZIP
bytes; unchanged rules beside other edits retain original XML attributes and
formula spelling (apart from a necessary priority change). Same-condition
rules prefer exact complete/style identities when recovering raw conditions,
so reordered differential styles do not swap. No client raw/provenance field
is trusted, and linked full-wire checks remain unchanged.

Evidence: /tmp/cf-cellis-source-contracts.log (37 new source contracts),
/tmp/cf-cellis-complete-targeted.log (100 reader/snapshot + 12 bridge tests
passed before the final attribute-preservation case), and
/tmp/cf-cellis-preservation-final.log (three final preservation cases passed).
The original reference RED is now GREEN. The source serializer SHA remains
 db38a4ca48933595db8019acce5f45b27f1fdff2f01d43bd6ae7abd84b16e18e.
A separate real-source oracle extracted six unchanged functions from fixed
univer-sync.ts via TypeScript AST and executed them in a VM: 636 supported
combinations matched the local projection, including all operators, numeric
blank behavior, text/wildcards, expressions and 3/20,000/20,001 cell budgets.
Probe: /tmp/cf-cellis-source-oracle.mts; result:
/tmp/cf-cellis-source-oracle.log. Extracted-functions SHA256:
771cee64d5c48b941949a69b9e1acff6a3dfc1e2c054145fc232c51869c971be.

## Open complex structural CF split work (read-only investigation)

Official sheets-formula FormulaRefRangeService.registerRangeFormula partitions
old coverage by affected direct ranges and formula dependency ranges. It
rebases each formula to its partition anchor, transforms references, normalizes
reference offsets to group equivalent formulas, then merges/sorts each group.
The CF UI controller maps group zero to Set(old cfId), later groups to Add(new
cfId). This is semantically necessary: Other!B1:B4 with =Sheet1!A1>0 splits when
a row is inserted before Sheet1 row 2; the Other coverage does not move, but
its relative dependencies cross the inserted boundary.

Full parity needs a shared deterministic structural planner from original
trusted rules plus the journaled operation, including cross-sheet dependencies,
relative/absolute/mixed references, formula thresholds and each group's own
anchor. Reuse official FormulaRefRange/Rectangle/LexerTreeBuilder behavior and
existing engine formula/reference shifting, with explicit boundary normalization
to fixed-source range semantics; do not flatten every split to the whole range.
Both frontend history and file-engine replay must derive the same partition.
Coverage must be exact (no lost or multiply covered cells), and formula tuples,
style, stopIfTrue and visibility must remain equivalent per partition.

Priority is a separate required fix: official addRule unshifts every new split
rule to the sheet front. Derived siblings must occupy their original parent's
priority slot as one contiguous group, keeping other rules in their original
order. Otherwise a sibling can overtake a higher-priority stopIfTrue rule.
Undo must remove derived IDs and recover the exact original rule/order; redo
must reuse the already planned IDs/order.

Ordinary groups can use the existing complete snapshot serializer. Linked
splits need server-side derivation of matching base/ext twins from the actual
original XML, preserving extension-only fields and generating unique IDs and
matching scopes/priorities. Client-declared group provenance cannot bypass
linked immutable checks. The current one-to-one trusted follower fix and
linked scope movement do not close this split gap. Required acceptance includes
cross-sheet dependency-only split, mixed/absolute references, multiple disjoint
ranges, bar/scale/icon formula bounds, overlapping higher-priority stopIfTrue,
full/partial deletion, undo/redo, GUI save/reopen and base/twin identities.

## Executable complex-split RED and implementation plan

New browser probe: frontend/smoke/workbook-cf-complex-split-probe.mjs.
From frontend directory, run `node smoke/workbook-cf-complex-split-probe.mjs`.
Its real openpyxl workbook has Source!A1:A5, Other!B1:B4, a higher-priority
TRUE red/stopIfTrue rule, then a lower-priority green =Source!A1>0 rule.
Insert before Source row 2. Other coverage must remain B1:B4, partitioned into
B1 with Source!A1 and B2:B4 with Source!A3 anchored at B2; the red stop rule
must remain ahead of both green descendants.

Current app is real RED (/tmp/cf-complex-split-probe-red.log): it retains one
unmodified dependent rule after the structure command. This is a known gap,
not acceptance of the refused split. Set CF_SPLIT_OFFICIAL=1 to observe original
official interceptor results through a browser-only route override, bypassing
only the local collector wrapper. No production source changes are made.
That mode captured an actual Set old-ID B2:B5/Source!A3 plus Add new-ID
B1/Source!A1, proving the unprefixed Source formula DID register its cross-sheet
dependency. The extra B5 is an official algorithm defect: its changed partition
is shifted even though only Source, not Other, was structurally edited.
Replaying those actual official mutations also moves the new sibling ahead of
the red stop rule. Evidence: /tmp/cf-complex-split-official-red2.log, both replay
mutations true, pageErrors empty. A workbook-ID prefix is not the cause here.

Implementation sequence and verifiable acceptance:

1. Build an ordinary-rule structural partition helper as local adaptation of
   the actual FormulaRefRangeService algorithm. Reuse the existing official
   lexer and Rectangle operations; extract only the pure boundary/dependency
   logic needed by the browser-safe engine, rather than simulate a second
   workbook. Inputs must include rule sheet, edited sheet, trusted original
   rules, formula tuple and operation. Apply geometry shifts only to coverage
   on the edited sheet; transform dependencies on the edited sheet for all
   rule sheets. Normalize insert boundary behavior through the exported engine
   shiftRangeReference. Verify cross-sheet example above, same-sheet relative,
   mixed/absolute references, quoted sheet names, disjoint coverage, deletions,
   and bar/scale/icon formula thresholds. Each output formula is rebased at its
   own sorted anchor. Verify exact union/no overlaps/no extra B5.
2. Integrate planner into actual engine applyRowColumnOps/applyCellShift for
   trusted source CF and browser trusted structural follower batches. Build all
   groups before applying any mutations. Use official Set/Add/Delete/Move
   mutations so the entire operation, derived IDs and priority moves enter one
   native undo item. Keep descendants contiguous in the original priority slot;
   test overlapping TRUE stop rule above, exact undo state/order and redo state.
   Actual file replay should produce the same ordinary wire groups, so save
   does not need a second compensating snapshot or phantom follow-up edit.
3. Handle linked groups inside the engine planner from verified original XML:
   clone each matched base/twin pair, derive unique IDs and matching new ranges,
   propagate/rebase cfvo formulas in both representations, preserve all other
   extension content and arrange priorities with ordinary descendants. Reader
   must verify every resulting unique pair. No client group/ID/raw field can
   authorize a linked edit; direct linked edit guard stays strict. Validate
   negative color/gradient preservation, independent extension bytes, same-RGB
   distinct dxfs, partial and complete deletion, and forged scope rejection.
4. Extend this probe to official command→undo/redo→draft reload→Python real
   save→revision reopen and re-evaluate rendered condition precedence. Check
   actual ZIP Other scopes/formulas/priorities, paired IDs, untouched other
   entries, and no phantom CF operation after reopen. Test only affected CF/
   structural contracts and both strict TypeScript configurations; finish with
   a single coordinated built GUI acceptance. Refusing split is interim safety,
   never the completion criterion.

The source source-version oracle and generated signatures must be recorded for
partition adapters exactly as cellIs was. A separate fixed-source investigation
is required for file gateway behavior: current structural.ts shifts f/formula1/
formula2/xm:f but not CF formula bodies, so implementing only frontend splitting
would leave headless edits inconsistent. Linked immutable restoration and the
fixed writer's preserved-priority strategy must be accounted for explicitly.

## Shared split planner implementation evidence

Shared structural CF partition stage: conditional-formatting-structure.ts is a
local pure interval planner. It splits coverage at formula reference transition
boundaries (including absolute/mixed axes, copy/fill off-grid transitions,
whole-row/column references and band edges), never enumerates cells, caps
rectangle multiplication before loops, preserves original parent priority slots
and reanchors each formula tuple to its own sorted group. Geometry shifts only
on the edited host sheet; cross-sheet dependencies transform without moving
host coverage. Adjacent equivalent pieces merge. Full-grid axes stay in bounds
and preserve inserted full-axis coverage. Lowercase references use the same
case-insensitive convention as fixed-source offset/structural transforms.

conditional-formatting-offset-source.ts extracts unchanged copy/fill functions
and constants from fixed domain/formula-shift.ts; only imports/grid constants/
RefPart plumbing are adapted. Full original file SHA256: cf1df9b29f0ab58607b4ba38b7ce6851232bdb649c9a69c24bde603e320d5360.
conditional-formatting-structure-xml.ts derives groups only from actual ZIP XML,
retains raw dxf IDs/attributes, clones source-verified linked twins with unique
IDs and matching scope/priority/formula tuples, preserves extension-only visual
fields and unrelated extension bytes. Final exported rules are checked for
exact semantic identity against the pure plan (not merely issue/count checks).
applyRowColumnOps reuses that planner for every affected rule sheet and journal
operation. Incomplete legacy CF retains its previous range-only contract and
never gains editable complete status. applyCellShift still retains its previous
intersecting-CF refusal; the pure/XML band APIs are tested but the cell-shift UI
pipeline is a separate integration boundary, not silently claimed complete.

This corrects specific upstream behavior: official dependency-only splits were
observed moving host coverage to B2:B5 and Add siblings unshifted above a higher
stopIfTrue rule; fixed gateway structural formulas omitted CF formula bodies.
The local frontend and file replay now share ordered partitions; no client
provenance fields authorize linked changes. Source writer remains byte-identical.
Evidence: tests/conditional-formatting-split.test.ts real ZIP cross-sheet insert,
delete REF partition, whole-column boundedness, mixed absolute axes, disjoint
anchors, all formula thresholds, linked derived pairs and extension visuals,
quoted literals/sheets, band coverage, preloop partition budget, lowercase refs;
/tmp/cf-split-final-green.log and /tmp/cf-split-final-types.log record final
engine evidence. Frontend owns native mutation history and its GUI acceptance.

## Follow-up cell-shift CF gap investigation

See NATIVE_XLSX_CONDITIONAL_FORMATTING_CELL_SHIFT_INVESTIGATION.md for fixed-source dispatch/CF-save provenance, five real engine RED contracts, the official browser priority RED, and the shared-planner follow-up plan. Production remains frozen. Insertion of cells has distinct coverage-gap semantics from insertion of entire rows/columns; current band planner behavior cannot simply be enabled by removing the CF intersection guard.

## Shared cell-shift engine implementation

Cell-shift CF stage now implements the previously explicit refused boundary.
Both pure planner and trusted XML materializer accept optional geometry:
'rows-columns' (existing default) or 'cells'. Cells move/delete only original
coverage inside the band and do not fill the inserted gap; full-axis coverage
is clipped to the valid grid without adding newly inserted blank cells.
applyCellShift now derives source-only CF plans on every rule sheet before
any package mutation, then overlays the exact planned CF XML after ordinary
cell/formula/notes shifts. The source linked/dxf/extension materialization and
semantic read-back identity check are shared with row/column operations.

Only CF base and x14 CF blocks whose source reader is complete are excluded
from the existing ranged-feature guard. For geometry=cells, incomplete CF
throws before a plan is registered; unlike the existing rows-columns legacy
fallback it cannot enter range-only handling. DV/filter/hyperlink/object/table/
shared-formula protections remain. A newly exercised x14 DV fixture exposed
that the old guard matched x14:sqref but omitted the standard xm:sqref; this
specific guard now checks both, so validated CF does not accidentally admit
an intersecting x14 data validation. Unknown CF types/attributes remain refused.

Evidence: twelve originally real RED cell-shift CF contracts progressed to
GREEN; source guard and mixed-axis semantic inverse cases extend the file to
fourteen. /tmp/cf-cell-shift-final-green.log covers these plus existing cell
shifts; /tmp/cf-cell-shift-final-engine-types.log and
/tmp/cf-cell-shift-final-frontend-types.log cover strict typechecks. The mixed
insert/delete test compares per-cell formula semantics, not equivalent
rectangle tilings or forced re-merging across independently persisted parents.
The browser collector/history/native-save acceptance belongs to frontend/root.
No fixed serializer changes, production build or dist/static updates made.
