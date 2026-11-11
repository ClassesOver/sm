# Word 均分行高：下一批设计与真实 DOM 探针

2026-11-10。设计完成后经root确认协议，已实现共享core与bridge的新step及定向测试；入口、Python及built验收由集成人员负责，不在本文冒称完成。

## 结论

使用真实 ProseMirror 行 DOM 的实际高度求平均；不得使用 `heightTwips` 声明值代替。保留固定源码的选区语义和强制 `atLeast` 规则。现有未标记的 `setTableRowHeights.steps` 只能表达“设置/清除并保留 exact”，不能冒充均分。建议在同一操作下新增一个明确的 distribute step，统一有序回放，服务端决定规则，客户端不能提交任意 `heightRule` 或 XML。

固定源码：`/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`；`apps/docs/src/renderer/editor/table-ops.ts` SHA256 `d47b69d719287f3126b97bb157b548451a234102351f95ddc6af3d44a5adbd`，`rowRange/zoomOf/distributeRowsEvenly` 约431–468行。

## 固定源码语义

- `selectedRect` 覆盖多行：只均分 `[top,bottom)`；只覆盖一个逻辑行（含普通光标）：均分整表。纵向合并单元格中的光标可能覆盖多行，按实际矩形处理。表节点选择经宿主入口转换成全表单元格选择。
- `tableStart + row offset` 传给 `view.nodeDOM`，取真实 `TR.getBoundingClientRect().height`；除显示 zoom，平均后 `Math.round(avgPx * 15)`，不是平均声明高度。
- 每个目标行同时设 `heightTwips=twips`、`heightRule='atLeast'`。因此原 exact 必须改成 atLeast；内容较高的行仍可超过目标，不能承诺最终每行视觉高度严格相等。
- 源码缺一个 DOM 时会忽略它、平均剩余行并写全部行。宿主应收紧为全部目标行均可测才提交，不能静默部分平均。

## 宿主 zoom 差异与测量方案

`frontend/src/docx-main.tsx` 的真实层级是 `.editor-scroll > .doc-zoom > .docx-canvas > PM根`；约396行把 `editor.view.dom` 传给 `createDocxViewCommands.page`。`docx-view.ts` 把 CSS `zoom` 写在 PM 根，而固定源码 `zoomOf` 只读最近 `.doc-zoom`。直接调用会把150%显示尺寸误当100%。

仅注入正确 zoom 仍不满足各档输出完全一致：Chromium 折叠1px边框在不同 zoom 下有像素取整。建议把“读取目标行实际高度”作为局部依赖闭包：沿用宿主分页的临时100%测量思路，在同一个同步段内记录并临时重置宿主负责的实际 zoom（PM 根；若 `.doc-zoom` 存在非1 zoom也一起记录），读取全部真实行 DOM，再在 `finally` 原样恢复属性值和优先级。期间不能 `await`；浏览器在下一帧前恢复，不改变草稿或PM属性。不要为了均分永久搬动整个宿主zoom所有权。

异步准备只在同步测量前做：等待 `document.fonts.ready`，等待目标表中未完成图片的 `decode`/加载，再等布局帧；图片失败或无法布局返回明确原因。记录原PM doc身份、表位置/身份、选区和宿主zoom；准备后逐一核验未变化，否则放弃本次操作。保存中、只读、草稿关闭、结构操作待保存等沿用现有行高入口门禁。测量时每行必须是已连接的 `HTMLTableRowElement`、属于当前表，全部高度有限且大于0；隐藏/脱离/零高行不可做部分平均。全部通过后才构建一个事务。

不要把缩放比例、DOM数组或截图当成服务端可信的几何证明。服务端接受的高度是经过边界校验的用户编辑意图。

## 最小共享协议演进

保留当前旧 step 原样兼容，添加显式新分支：

```ts
type TableRowHeightStep =
  | { top: number; bottom: number; heightTwips: number | null }
  | { kind: 'distributeTableRows'; top: number; bottom: number; heightTwips: number }
```

操作外层仍为 `setTableRowHeights`，携带现有 blockId、expectedObjectSha256 与 `steps`。旧分支严格3键；新分支严格4键且 kind固定，不接受 `heightRule`、自定义XML或额外字段。`heightTwips` 是100% DOM测量后的正安全整数且不超过31680；top/bottom是逻辑行半开区间。无需把客户端单行/整表选区再传给服务端，范围由前端固定源码语义生成，服务端只验证有效行带。

core按现有顺序执行：旧step设置保留当前exact，清除归null；新step把目标高度设为实测值（不按节正文高截断），并无条件设atLeast。随后旧step以当时有效rule为基础，不能恢复旧exact。一步均分不能拆成“clear+set”伪造，因为这会丢失可审计的真实意图并增加计数/历史复杂性。

bridge保留现有XML补丁策略，但新step涉及的已有 `w:trHeight` 必须同时把 `w:hRule` 改成atLeast；省略rule可保留省略（OOXML默认atLeast），旧exact/auto必须改；仅改所需属性值，不重建整表/单元格/段落。新增trHeight用atLeast。回读验证最终effective heights/rules与全表actual XML。保留未选中auto/0原字节及cantSplit/header/内容。

前端草稿校验、operation收集/恢复、共享core、TS bridge输入/输出和Python边界同时接受新分支；不要只改UI或放宽未知字段。1–50 steps及现有100行/30列/1000格限额保持。undo/redo通过同一PM事务和原始有序intent恢复；重开必须仍携带明确distribute step，不能降级成保exact的旧set。

## 服务端边界

- 从原文件、对应表和有效节重算允许的正文高度上限，客户端不得提供上限。保持现有节/多栏适用性规则，不借机放宽其他边界。
- 验证原文件SHA、对象SHA、行带、整数、step精确字段、step数量和合法TableMap；顺序执行同一core，不接受client最终XML。
- 原表readonly原因（修订、歧义行属性、非法span等）保持；纵横合并及全部被rowspan覆盖的逻辑行在合法结构下可测，不能因为没有独立可见cell就剔除该行DOM。
- 旧set继续按可信节正文高度clamp；distribute遵循源码不按节正文高截断，实测高于正文但≤31680时保留。超过31680尚未覆盖，应明确提示无法均分，不截断后冒称完整支持。31680是当前桥接合法OOXML模型的既有边界。
- 测量是客户端行为，服务端不能证明它确为平均值；它只能验证该高度可作为合法行高编辑。伪造测量不会扩展权限。
- 不改变产物发布和验收非阻断契约。

## 已执行真实浏览器探针

独立目录 `/tmp/word-distribute-row-dom/`：`probe.ts` 创建真实PM EditorView和真实table/tbody/tr；直接导入固定源码 `distributeRowsEvenly`。`build.mjs` 只打包独立探针，`run.mjs` 启动headless Chromium，结果是 `results.jsonl` / `run.log`。没有生产构建、生产源码修改或整套测试。

执行：

```sh
node /tmp/word-distribute-row-dom/build.mjs
node /tmp/word-distribute-row-dom/run.mjs > /tmp/word-distribute-row-dom/run.log
```

Chromium `140.0.7339.16`，13向量通过。内容为真实中文文本段落、固定表宽、单元格padding和折叠1px边框；三个逻辑行的100%真实高度27/67/47px。该探针使用最小PM DOM schema，**不是**完整宿主CSS/DOCX保存验收，不能代替后续built链路。

| zoom位置/比例 | 原源码输出twip | 除真实zoom后的twip | 临时100%真实DOM测量twip |
|---|---:|---:|---:|
| wrapper或PM根100% | 705 | 705 | 705 |
| wrapper150% | 700 | 700 | 705 |
| wrapper75% | 710 | 710 | 705 |
| PM根150%（实际宿主） | 1050 | 700 | 705 |
| PM根75%（实际宿主） | 533 | 710 | 705 |

每档覆盖普通光标整表及前两行CellSelection；验证真实connected TR、实际高度>0、source事务强制atLeast且未选第三行不变。额外故障注入隐藏第二行nodeDOM：源码仍返回成功并把555写到全部行，证明需要宿主全量测量守卫。

## 验收向量与当前边界

1. core/bridge定向（本批已执行，下段给出证据）：exact→distribute为atLeast；distribute→set仍atLeast；set→distribute；distribute→clear→set；混合选中/未选中auto0、auto正值、rule省略；越界/未知kind/额外heightRule拒绝；保留非height原XML和包内其他parts。
2. 真实built入口：相同DOCX、相同选区在100/150/75%输出完全相同twip；比较提交steps与下载后直接trHeight，并刷新草稿、撤销/重做、保存/重开回读。检查没有永久zoom变化、没有只显示控件未登记意图。
3. 真实内容：高度不同的多段文字、精确行高裁剪、图片、字体加载前后、padding/边框、横合并、纵合并、全部被rowspan覆盖的空行；只选一行/两行/全表/表节点/纵合并光标。
4. 真实故障：某行DOM缺失/不连接/零高；图片失败；等待字体过程中表、选择、zoom变化；测量抛异常。验证不登记草稿、不产生半事务、zoom一定恢复，用户获得具体原因。
5. 只运行被改入口的定向合约与必要built smoke；不要重复完整测试。完成后更新该文档，将“尚未执行”与实际结果区分。

## core/bridge 实现验证（已完成并冻结）

共享类型已接受严格4键 `distributeTableRows`，旧3键不变。新step保留2000twip实测值，即使节max=1000；强制atLeast；旧set仍clamp。bridge只改直属trHeight的val及必要rule，未选行保持原样。新分支不能提供heightRule，null、0、小数、未知kind、31681均拒绝。

先RED：`/tmp/row-distribute-core-red.log`、`/tmp/row-distribute-bridge-red.log` 均由尚不支持新step失败。GREEN：core文件5例通过 `/tmp/row-distribute-core-green.log`；新增bridge2例通过 `/tmp/row-distribute-bridge-green.log`；其余bridge回归定向通过 `/tmp/row-distribute-legacy-bridge-green.log`；限定tsconfig无错误 `/tmp/row-distribute-types.log`。没有重复完整测试或构建生产bundle。混步set→distribute→set、distribute→clear→set及exact/auto/省略rule和真实DOCX保存回读、非document.xml包件保留已验证。完整入口与保存HTTP链路仍需由root/UI任务验收。
