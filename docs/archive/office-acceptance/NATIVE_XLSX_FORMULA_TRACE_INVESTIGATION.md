# XLSX 公式引用追踪：只读调查与最小方案

2026-11-10。本次仅静态取证和方案，不修改生产代码、不运行测试或构建，未计实现或验收通过。先核对最新审计尾部和八项队列；没有把历史已完成的只读表格删除、定义名称、分页预览或隐藏列缺口重新安排。

## 确认缺口

本地 `frontend/src/workbook-ribbon.ts:474` 的公式审核组中，只有 `toggle-show-formulas` 有可执行 command；`trace-precedents`、`trace-dependents`、`remove-arrows` 仅创建标签。按钮创建处 `:1231` 将 `item.command === undefined` 置为 disabled；`workbook-main.ts` 没有三条命令分支，当前工作簿模块中没有追踪 helper。`docs/parity/2026-11-10-explicit-ribbon-gaps-inventory.md` 也记录本项；八项接续队列没有重复负责人。

建议优先这三项：它们直接帮助解释已有公式，固定源有完整可复用算法与绘制层，能复用当前已验证的官方范围浮层；不需要先引入外部连接、查询授权或新的文件写入协议。“错误检查/监视窗口/外链面板”同属组内但不顺带纳入。

## 固定源事实

固定提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，来源根 `/home/junge/pros/genoffice-source-full`：

| 文件 | 实际行为 | SHA-256 |
| --- | --- | --- |
| `apps/sheets/src/renderer/ribbon-actions.ts:1095–1182` | 选区左上格为目标；引用追踪读取其公式，从属追踪扫描当前快照；跨表引用仅计数反馈；重复调用累加浮层；移除箭头逐项 dispose。 | `e4effd7feda2b4e9c6f8feb1b7f976b0b6325a80a2e690cb4fd17e46888efa11` |
| `apps/sheets/src/renderer/trace-arrows.tsx:45,110,172` | `collectPrecedents` 去重同表区域，整行/列引用按已用范围裁剪；`collectDependents` 遍历公式，排除目标自身；`installTraceArrows` 使用 `registerComponent/addFloatDomToRange` 绘制蓝色边框及 SVG 箭头。 | `eadb96ce844dd76c43b3c1c175d649a25c84ba08f4cd7ae738965dee19e7c673` |
| `apps/sheets/src/renderer/formula-closure.ts:61–113` | `parseReferenceToken/parseFormulaReferences` 解析 A1 区域、整行整列，跳过双引号字符串，沿用 gateway 的引用正则和 qualifier 语义。 | `56382524c6ce217900a0f231d8eb7422b0f2bf97b7788b2394bae99f87883c21` |

固定源是公式文本引用追踪，不是完整计算依赖图：定义名称、结构化表引用和间接动态引用没有在上述 collector 中展开，不可宣称这些对象已完整支持。跨表只报告数量，不绘制跨表导航箭头。源中依赖 lazy preload 的说明不适用于本地整份快照加载，不能复制为虚假的“已加载区域”状态。

当前安装的 `@univerjs/sheets-formula` facade 类型未见公开 precedents/dependents 查询入口；现有 `registerComponent/addFloatDomToRange` 能直接承载源绘制方式。调查没有因此引入内部依赖树或另造公式解析器。

## 最小实施边界与验证

1. 独立模块移植源 collector、箭头呈现及必需的引用 parser，复用已有引擎 `FORMULA_REFERENCE_PATTERN/qualifierMatches`；不迁入整套 streaming closure/edit journal。先用固定源直接函数与代表公式对照，覆盖绝对/相对、带引号表名、字符串、范围、整轴、跨表、自引用及重复去重。名称/结构化/间接引用边界须明确反馈，不能把空结果笼统说成“没有依赖”。
2. controller 管理实际 workbook/worksheet 身份、唯一组件 ID 和 dispose；挂载失败回收已注册项。移除、替换、关闭释放浮层，编辑/结构变更后的旧坐标不得继续显示为有效结果；可选择清除并提示重追踪，避免为了本批引入持久依赖图。只读/保护表可查看，按钮及反馈不触发 markDirty、历史、草稿或文件操作。
3. main/Ribbon 只接三条命令，受影响窄测试先 RED→GREEN。真实浏览器验收公式选区→引用边框/箭头→从属→移除，覆盖冻结、缩放、RTL、隐藏轴及切表/关闭清理；同时核对快照、草稿、撤销栈、保存状态和下载 SHA 不变。尺寸采样和全快照扫描的预算需先明确并如实反馈截断/拒绝原因，不能输出貌似完整的部分依赖。

范围：不接错误检查、监视窗口、外部链接管理，不新增 XLSX 公式或浮层文件持久化，不扩展 Plotly，不预记完整 XLSX 对齐。实际表现与生命周期由窄测试和新 built 场景证明后再更新验收。


## 接续实施状态（待统一 built 验收）

上述只读调查后 root 明确授权实施三入口。新增
`frontend/src/workbook-formula-trace.ts` 与 controller，main/Ribbon 已接
precedents/dependents/remove-arrows；未顺带接错误检查、监视窗口或外链管理。
源的 parser/collector 按上述固定文件迁入，本地复用既有引用 pattern/qualifier；
没有依赖整套 streaming/edit-journal。源导出函数直接 bundle 捕获18个输入/输出
向量，保存为 `workbook-formula-trace-source-vectors.json`；构建源向量时仅裁出
formula-closure 的纯parser片段，未执行其closure/lazy工作流。

本地适配：扫描最多20000个已存储单元格；单次及会话累计最多200个浮层，
单跨度20000行/2000列，超过即明确拒绝而非画一部分。名称/结构化/INDIRECT/OFFSET
提示不完整，跨表只计数；空结果不冒充复杂依赖不存在。官方range float与源SVG
箭头保留，RTL横向坐标镜像、隐藏轴使用0尺寸；安装失败回收已有注册。
controller按真实Worksheet身份隔离，切表/替换/销毁回收；sheet mutation和
Undo/Redo清除静态旧依赖，提示重新追踪。仅会话显示，不写文件/草稿/历史。

证据：`/tmp/trace-source-vectors.log` 固定源18向量生成；
`/tmp/trace-red.log` 新helper/controller缺模块RED，
`/tmp/trace-main-red.log` main/Ribbon两项RED；
`/tmp/trace-controller-guards-red.log` 空/累计guard RED。
`/tmp/trace-final-tests.log` 51项Vitest GREEN（helper4项含18向量、controller2、
真实main1、Ribbon44）；RTL隐藏轴实际SVG坐标、安装失败回收、真实
只读snapshot/draft/history/status不变、工作表显示变更清理已覆盖。
`/tmp/trace-types2.log` 窄配置读取main/ribbon/helper/controller及tests，exit0；
该types记录不代表完整生产build。

未运行frontend build或built smoke；统一产物由root协调，静态箭头实际滚动、
冻结、缩放、RTL和文件SHA证据须在新dist验证后再登记验收，当前不称最终交付。

追加伪引用边界：`Table1[A1]` 的列名形似A1，以及INDIRECT/OFFSET参数不能
被直接画成已确认依赖。`/tmp/trace-complex-red.log`先真实RED，planner现对复杂
前置公式整体拒绝绘制并说明限制；从属扫描跳过复杂候选公式，同时保留普通
直接公式的结果并说明不完整。raw collector继续与源18向量一致。最终
`/tmp/trace-complex-green.log` helper5+controller2 GREEN，
`/tmp/trace-main-both-green.log`真实main前置/从属/移除及清理GREEN，
`/tmp/trace-types-final.log`窄types exit0；Ribbon44使用此前绿色结果，未重复
完整测试。源代码冻结，新的独立built smoke准备后等待root统一dist，不提前运行。

## RTL 首次 built 失败与修复（最终 built 待验证）

统一产物首跑 `/tmp/formula-trace-built-smoke.log`：Plain/Frozen/Zoom150通过，
RTL!D6（`=SUM(A1:B1)+B4`）超时；`/tmp/formula-trace-built-U6gA0c/failure.png`
可见缺失箭头。只读诊断 `/tmp/formula-trace-diagnostic.log` 表明官方 float 根
容器和 SVG 的真实 width=0。官方 `_createRangePositionObserver` 以
endColumn.right-startColumn.left 算宽，RTL 跨列产生负值；SVG镜像并不能修复。

本地只在RTL用视觉左上单格(startRow,endColumn)作为官方锚点，domAnchor传
未缩放的可见轴尺寸和，仍由官方处理缩放和滚动。完全隐藏范围不绘制；官方会
将合并主格替成mergeInfo，故合并锚点或箭头端点明确拒绘并返回原因。
`/tmp/trace-rtl-anchor-red.log` 复现官方负宽，
`/tmp/trace-rtl-boundary-red.log` 复现隐藏/merge缺少拒绘，最终
`/tmp/trace-rtl-boundary-green.log` 9窄测试GREEN；
`/tmp/trace-types-rtl.log`针对main依赖类型检查exit0。

新smoke增加RTL150Frozen、RTLHiddenEnd（A1:B1终列B隐藏，D6目标可见）及
RTLMerge主格锚点拒绘。它从真实画布选择边框像素取目标中心，核对每条前置
箭头末端；RTL150Frozen滚动后再次核对选择中心与箭头，不能仅以宽度非零验收。
这些新增复合场景尚待重建dist后的真实结果，当前不声明通过。

冻结跨pane后续验证发现：`/tmp/formula-trace-built-smoke-rtl-fixed.log` 的真实
画布选择框比对在Frozen失败（`/tmp/formula-trace-built-OFye2Q`）。官方range
float会按pane裁剪/移动边界，源单一完整SVG viewBox不能同时匹配两端位置。
因此改为每箭头两个官方单格float，读取它们实际可见DOM裁剪矩形中心，仅由
host SVG连线；不复制viewport坐标算法。仅监听当前float祖先style/class变化，
合并单次rAF刷新，销毁释放observer/frame/SVG；没有常驻轮询。视口外端点
不画，并明确提示滚动到可见后恢复。高亮沿冻结边界最多拆4段。
`/tmp/trace-pane-red.log`→`/tmp/trace-pane-final-tests.log` 10窄测试GREEN
（含真实main只读契约）；`/tmp/trace-types-pane-final.log`exit0。
当前等待root统一dist后的复合built实测，前述单range修复不能当最终证据。

DOM连接点采用官方单格float在当前pane中**实际可见裁剪部分的中心**，不宣称
是被裁剪前完整单元格中心。端点完全离开可见区域时不画线，回到视口后按新
官方DOM位置恢复。ref解绑/重绑先释放同端点旧MutationObserver，防止主题或
React刷新累积监听；`/tmp/trace-ref-red.log`→`/tmp/trace-ref-green.log`窄回归。
