# PPTX Normal幻灯片栏键盘导航增量

基线：`code` b65c5e8（#237）。固定源：GenOffice f8c17004，
[源keyboard-actions.ts:328起](https://github.com/genspark-ai/genoffice/blob/f8c17004fb730df11f0f743164ffd8b4281bb38c/apps/slides/src/renderer/keyboard-actions.ts#L328)。本切片不是PPTX/四格式完整对齐。

## 实现范围

Normal视图直接聚焦页按钮时，ArrowUp/Down、PageUp/Down按真实当前页在最新DOM页序移动，Home/End首尾。边界消费但不重复点击或冲刷备注。通过现有同步click路径，只有切页成功后重新查询已重建的按钮并恢复焦点、nearest滚动。原click中的notes.flush→selectedSlide→renderSlides→renderInspector完全保留；不新造导航状态或保存协议。

仅接直接焦点，忽略修饰键/Shift、IME、已消费事件、modal、隐藏/禁用按钮、非Normal、管理按钮和dispose后的事件。保留native ol/button、Tab次序和CSS；当前页加aria-current=page。无脏备注时不更改草稿或保存；脏备注导航会沿既有click合同flush，不能宣称所有导航零写入。

## 分层验证

证据：`/tmp/office-next-evidence`。本工作区从原前端package-lock执行npm ci --ignore-scripts，595包，锁文件未改；不更新全局环境。

- `rail-integration-red.log`：真实slides-main DOM入口ArrowDown未被消费，期望true实际false；不是静态源码断言。
- `rail-green.log`：最小接线后controller与真实宿主2文件9项通过。
- `rail-related.log`：controller、Normal/Sorter视图、大纲/阅读、notes宿主与notes组件5文件47项通过；覆盖备注输入法否决、合法未提交备注归原页、重建焦点、Tab焦点不同仍按selected计算、DOM重排/非连续ID、边界、modal/IME/修饰键/管理按钮/dispose。Canvas在集成fixture中模拟，不能据此称真实画布验收。
- 新controller及其测试独立strict TypeScript检查通过（`rail-focused-tsc.log`）。
- 完整前端tsc未完成：默认进程被kill，2GB限制OOM，3GB限制exit137且无诊断。已停止重复尝试，需可配置云环境复核完整tsc/构建/原预算；本批不声称完整类型检查通过。
- Chromium辅助长列表实际可见性验证未执行成功：运行环境socket() Operation not permitted，允许范围内一次提权重试同样失败，已停止。DOM测试只验证nearest调用，不冒称长列表像素可见或真实浏览器通过。

没有修改XLSX产品代码、PDF导航、slides-find-replace、AI或#236 task_execution/Word绑定。没有真实Codex连接、保存下载重开、生产鉴权、推送、PR、合并或部署；纯视图导航不要求生成PPTX保存回执。独立审查结论另补，当前仍待阶段整合及完整前端云验证。

## 独立审查与冻结

Astra实际审阅代码与测试，确认无重大/重要代码阻断；独立复跑controller 5项与slides-view-modes 7项，12/12通过，diff-check通过。随后按建议仅修测试卫生：afterEach可靠恢复scrollIntoView原prototype descriptor，删除测试名中未实测的detached声明；该controller 5项再次通过（rail-review-hygiene.log）。产品代码未因审查变化。最后ARIA专项2项通过（rail-final-aria.log）；focused strict tsc最终退出0（rail-focused-tsc-final.log）。这仍是可阶段冻结交云复验，不是完整构建或真实宿主浏览器验收完成。

## 最新 code 重放后的独立云验收（限定范围）

本节覆盖上文的本地 pending 状态，不删除原有失败或将早期实现改称首次全绿。
在 `code@0ce3aa10e975100fbbac7abf1ea1e85a925beeb6`（已合并 #236）上，
无冲突以 `cherry-pick -x` 重放 `34ecf23`、`3202edb`：
`92a9d6a`、`a9d3d19be829e64d6bc5ca927054d95be7fa9fa4`。
实测整合 tree：`78d5311f20de56619090b2428eb2c2fc1fc2c3d3`。
前端、scripts、pyproject 和锁文件内容与原 `3202edb` 相同，但仍对这个
精确新树实际验收，没有仅凭内容相同外推通过。

- 五份相关定向测试一次：47 passed，11.62s，exit 0。
- 真实 `slides-main.ts` 完整导入闭包：1190 文件、258 项目源码；strict/noEmit
  保留，沿用原 skipLibCheck；diagnosticCount/errorCount=0，exit 0，旧工作树源码
  引用为空。这不是全前端 tsc、生产 build 或预算检查。
- 真实 Chromium 生产宿主六组本轮一次通过，exit 0，pageerrors=[]：
  `long-rail-repeat-and-nearest`、`home-end-boundaries-no-notes-flush`、
  `selected-vs-tab-and-current-dom-order`、`notes-ime-veto-and-error-focus`、
  `valid-uncommitted-notes-original-page`、
  `guards-ime-modifiers-modal-controls-dispose`。
- 四份变更入口/控制器/测试的 SHA256 已在本地与云身份记录逐项核对；运行入口及
  响应产物绑定精确整合源码，工作树 clean、临时服务与链接已清理。

### 严格几何边界和全部控制台记录

Home 后实际 `current=0`、焦点为页按钮0、aria-current仅一个、scrollTop=66。
按钮 top=210.5/bottom=246.5，容器 top=211/bottom=936，所以上沿仍有
**0.5 CSS px 裁切**：原严格 visible=false，仅 visibleWithinOneCssPixel=true。
1px 是临时验收脚本增加的量化容差，不是 spec 的明文保证。本证据仅支持实际
nearest 调用和 bounded nearest 可见性，不声称严格完全可见，不因测试通过隐去裁切。

控制台并非空白：Chromium Local Network Access 阻断 localhost Vite HMR 的
WebSocket，console error 12条，另 Vite failed-to-connect console error 6条；
缺 `download` 图标 warning 6条；空值不符合 CSS color 格式 warning 36条。
这些均保留在原记录中，与 pageerrors=[] 分列，不称 warning/error-console-free。

### 早期 fixture 失败及独立归因

旧 `3202edb` 的历史为：加载失败 exit1（0行为场景执行）→首行为轮3过/3失败
exit1→仅三项定点复核3过 exit0，而非一次六组全绿：

1. 首个合成 RenderSlide 缺必须的 background，违反 render-tree 强类型及
   build-slide/resolveFill 契约；fillToKonva 直接读 fill.kind，因此加载失败。
   补 `{kind:'solid',color:'#ffffff'}` 是 fixture 修正，非产品修复。新整合树
   fixture 另补必需的 scale:1，符合 width/height/scale/background/nodes 最小契约。
2. Home 的严格几何失败就是上述0.5px事实；复核新增1px容差，不能将其说成原断言通过。
3. 临时 prepend DOM 行20后 Home 会同步走原 click/renderSlides，将列表按真实 order
   重建为0…31；下一键应为21，非脚本原先误期望0。复核同时断言重建后的最新 DOM。
4. 守卫组开始前已从上一合法备注场景恢复1份同身份草稿，组前/后相同且零新
   storage/click/scroll；原期望绝对0是组间 localStorage 污染。复核隔离存储，
   并额外明确让rail聚焦后测试modal、补dispose断言，没有删除不新增草稿的要求。

产品与仓库测试未为上述复核修改；未增加随机等待或随机重试。原加载后180ms及
连续键25ms间隔保留。新整合树六组完整执行一次与旧三项复核分开记录。

### 核验和未覆盖项

63项证据清单独立复核匹配，清单SHA256：
`3c4ad77f20c77d3f84ad42571c8e2aecdc54b1606970fe7056c8085de3c8ba29`。
精确命令、类型结果、源码/产物绑定、原始几何和控制台轨迹均已保留。
这次只用离线合成 deck 与合法最小空nodes render-tree，证明rail/宿主接线，
不证明真实PPTX导入/保存/导出、OS原生IME、完整渲染保真、全前端构建、全部四格式
能力或任何真实Codex/provider接通。没有安装依赖、改锁、推送、PR、合并或部署。
后续只有本记录的文档跟进；源码/测试/配置须与上述已验整合树保持完全相同。
