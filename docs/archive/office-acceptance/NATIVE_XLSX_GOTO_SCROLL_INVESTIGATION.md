# XLSX 定位远处目标后视口不滚动：只读调查

2026-11-10。结论：这是宿主遗漏固定来源 reveal 步骤的真实导航差异。
当前 `setActiveRange` 完成跨表与选区更新，名称框随之变化，但该 facade 不
要求渲染器滚动。此结论有 built 可见结果和当前安装包源码双重证据。
本调查只增加文档，不修改生产、测试或构建文件，不宣称已修复。

## 最小真实复现与证据

来源文件 `/tmp/cross-highlight-built-AAfR14/source.xlsx` 含普通 Far 工作表，
`AA26010` 有 extent sentinel，因此原生行数足够，不是 1000 行最小投影上限。
`Z25001` 本身为空。来源行数投影规则在
`frontend/src/workbook-vendor/core/univer-data.ts:165`：
`min(1048576, max(1000, maximumRow + 100))`。

1. 用该文件进入真实构建原生编辑器。
2. Home → 定位，输入 `Far!Z25001` 并确定。
3. Far 标签已激活；名称框显示 `Z25001`；画布却仍为第 1 行、A 列起始视口。
4. 不改任何数据，按 ArrowDown 再 ArrowUp，原生键盘导航把目标滚入视口。
   开启阅读高亮后该远处行/列确实可见，检测 85182 个高亮像素；关闭完全恢复。

第 3 步截图：`/tmp/cross-highlight-built-spnz1C/failure.png`；对应日志
`/tmp/xlsx-cross-highlight-built-far-navigation-failure.log`。截图记录名称框、
行列头和活动标签，可区别“没有选中”与“选中了但没滚动”。当时 off/on
画布逐像素完全相同，因为活动行列都在可见范围之外。第 4 步最终截图：
`/tmp/cross-highlight-built-AAfR14/far-blank-on.png`，最终日志
`/tmp/xlsx-cross-highlight-built-smoke.log`。前后本地草稿、历史和保存态不变。

## 固定来源与宿主遗漏

固定仓库 `/home/junge/pros/genoffice-source-full` 的 HEAD 已重新核对为
`f8c17004fb730df11f0f743164ffd8b4281bb38c`；不是浮动上游。

| 位置 | 现有行为 |
| --- | --- |
| 源 `apps/sheets/src/renderer/data-tools-actions.ts:145` | `goToReference` 校验引用、结束正在编辑的旧单元格、解析 range、选择目标 |
| 同源 `:166` | 选择后显式 `void revealCellBelowFreeze(target, range.getRow(), range.getColumn())` |
| 同源 `:170` | 官方 `ILayoutService.focus()` 交还 grid 焦点 |
| 同源后续步骤 | 按目标显式 loadVisibleRange，服务源应用的 lazy workbook |
| 宿主 `frontend/src/workbook-main.ts:497` | 解析引用、取 target、必要时切表、`workbook.setActiveRange(range)`，随即报告“已定位” |
| 宿主 `frontend/src/workbook-goto.ts:132` | 成功关闭 modal 后 `onNavigated` → 官方 grid focus，焦点补齐已存在 |

宿主未调用 reveal helper，也没有替代的 scroll。纯 `goto.ts` 的引用解析
迁移本身不是问题；遗漏发生在 main 的执行接线。
`frontend/src/workbook-vendor/grid/sync.ts` 也没有该 reveal helper。
源文件 SHA256：

- data-tools-actions.ts：`afa7d06f2579afba8345a344fc1a6758f6dc9d3fb5335e5d36d6c6fd14054500`
- univer-sync.ts：`677f67710889e5d17e5e643177090757cd89534997589930976e78dd4e8cbf4e`

固定源 `univer-sync.ts:917` 的 `revealCellBelowFreeze` 使用官方
`scrollToCell`、`getVisibleRange`，先判目标是否已可见；否则滚向目标前一行，
最多 4 次、每次间隔 60ms 校正视口过冲/不足；较新 reveal 取消旧校正。
RTL 先等原生滚动后检查目标是否可见，避免再次大幅跳动。源注释指出普通
scrollToCell 在自定义尺寸冻结区可能定位偏移；这是后续修复须验证的风险，
本轮没有真实复测所有冻结高度组合，不能直接把注释当宿主全场景实测。

## 当前实际 facade 和 scroll controller

宿主固定 `@univerjs/sheets` / preset 版本 0.25.1；固定 GenOffice preset
声明 `^0.25.1`。以下证据来自宿主实际安装包，不假定选区 API 隐式滚动：

- `node_modules/@univerjs/sheets/lib/es/facade.js:7468`
  `FWorkbook.setActiveRange` 切换目标表后发送 `SetSelectionsOperation`。
  参数仅 unitId、subUnitId、selections；**没有 reveal 字段**。
- `node_modules/@univerjs/sheets-ui/lib/es/index.js:7270`
  scroll controller 监听该操作，但仅当 `p.unitId` 匹配且 `p.reveal` 为真
  才 `_scrollToSelection()`。因此当前 facade 选区操作不会触发这条滚动分支。
- `node_modules/@univerjs/sheets-ui/lib/es/facade.js:877`
  `FWorksheet.scrollToCell(row, column, duration?)` 是可用官方 API，委托
  `SheetsScrollRenderController.scrollToCell`。同文件 `:862` 提供
  `getVisibleRange()`，`:883` 提供 `getScrollState()`，可以直接核对视口。
- `node_modules/@univerjs/sheets-ui/lib/es/index.js:7257`
  `scrollToCell` 用当前活动表 freeze x/y split 调整索引后发 ScrollCommand。
  必须先确保目标表已活动，不能向未活动表假定独立滚动。
- 该 controller 的选区扩展/键盘路径会显式 reveal（`:7300` 附近），这解释
  为什么后续真实方向键可使远处目标进入视口。

这不是新高亮 extension 吞事件：名称框反映真实新选区，且同一目标在原生
键盘滚入后高亮正常。也不是异步多等一帧即可修复：调用路径缺少滚动请求。

## 最小后续修复建议（尚未执行）

在现有 goTo main callback 的 `setActiveRange(range)` 之后，复用固定源
`revealCellBelowFreeze` 的官方 facade 方案，保持现有关闭模态框后交还焦点。
不要依赖 `setActiveRange` 自动滚动，不改变文档数据以制造可见结果，也不
只在探针用键盘绕开。先添加真实 main 接线 RED 和独立 built 远处可见断言。

普通目标单次 `scrollToCell` 足以发起请求，但完整对齐应包含固定源已经
处理的冻结尺寸/RTL问题；不应仅接一行后宣称这些场景均已通过。迁入 helper
时将“最新导航获胜”的状态绑定本次宿主实例并在 dispose 取消，避免复用
源全局 generation 导致同页编辑器互相取消。宿主文件现为完整载入，不应
仅因源代码存在就移入其 lazy loadVisibleRange 系统。

验收应分别断言：远处目标选择正确且可见；跨表/同表；冻结自定义行高和
列宽、RTL、150%缩放、已有可见目标不无故跳动；快速连续导航最后目标
获胜；关闭/替换不会延迟滚动旧实例。区域/整行/整列以目标首格为 reveal
锚点，不能强求巨型区域全量可见。只读、保存态导航继续可用，完整 snapshot、
NativeDraft、undo/redo、保存态及下载字节不变。编辑中跳转的提交顺序是源
另一个差异点，需独立复现后再决定范围，不能在本轮调查顺手更改。

本轮未跑新完整测试或重建；证据复用已完成的真实 built 失败与成功对照，
并静态追溯实际 facade。上述修复建议仍待实施与验证。

## 2026-11-10 修复实施，等待 built 验收

已按上述范围实施宿主独立 `workbook-goto-reveal.ts`，main 在保留原
`setActiveRange` 后委托官方 facade reveal。来源、宿主 SHA 及适配记录已补
`frontend/src/workbook-vendor/SOURCE.md`，不混入 vendor 目录哈希。
实际可见才返回成功消息；未能显示/接口异常保留选区并反馈原因。
每实例 generation/计时器在新导航、来源替换和 dispose 取消；迟到的旧失败
不覆盖新导航，切表或手工改变目标选区会停止旧校正。Frozen viewport 通过
官方 map 检查，目标本已可见时不无谓滚动。未引入源 lazy loading 系统。

RED：helper 缺模块失败；main 真实接线明确观察到 reveal 未调用（0 次）失败。
GREEN：helper7（远处/已可见冻结/冻结尺寸偏移/RTL/失败/隔离销毁/替换），
main3（只读跨表snapshot/draft/history不变及false/exception反馈），迟到回调1，
原焦点兼容4；`tsc --noEmit` session76271 exit0。定向日志：
`/tmp/xlsx-goto-reveal-green.log`、`/tmp/xlsx-goto-main-feedback-green.log`、
`/tmp/xlsx-goto-stale-green.log`、`/tmp/xlsx-goto-focus-green.log`。
不重复完整测试、不自行build。

生产代码已冻结，独立 `smoke/workbook-goto-scroll-built-smoke.mjs` 已准备并通过
node语法检查：只读普通/自定义冻结高宽/150%/RTL/Far源直接定位Z25001，
**不按方向键**，同时核对显示成功反馈、实际行列高亮像素、关闭恢复、
完整draft/history/save态、真实下载SHA、静态JS200/SHA和pageErrors。
等待root统一build后执行，目前不宣称该修复built验收通过。

## 最终结论：本专项已通过

root统一build后严格built session66605明确exit0，五场真实受保护来源
直接Z25001均可见，不再用方向键补滚动；像素恢复100%，230JS200/SHA，
下载前后与来源SHA一致、save0/pageErrors[]、draft/history/save态不变。
完整证据与顶层editingEnabled=false仍禁止整个编辑器挂载的现有限制见
`NATIVE_XLSX_GOTO_SCROLL_ACCEPTANCE.md`。本专项不再属于“尚未修复”状态，
前面的只读调查/等待验收段为时间顺序留档，不覆盖此最终结论。
