# PPTX 固定源公式文本框对齐

日期：2026-11-13。固定源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮按当前源码重新核对，未沿用过期盘点结论。范围为固定源已有的 Unicode 数学字体文本框，不是 OMML、LaTeX 解析或专业公式对象。

## 先核对经典批注，避免重复交付

| 固定源源码链 | 当前本地链 | 本轮结论／剩余边界 |
| --- | --- | --- |
| Ribbon.onToggleComments → App.getComments → CommentsPane | `bridge/edit-pptx.ts` 的 inspectClassicComments、`slides-main.ts` 的 sourceComments/renderComments、`slides-comments-pane.ts` | 经典批注查看已接通，不再视为缺口 |
| CommentsPane.onAdd → App.addComment → sessionTxn → engine.addSlideComment | bridge.validateClassicCommentEdits/applyClassicCommentEdits；main.changeComments/commentEdits；Ribbon.newComment | 根批注新增已接通，复用现有草稿和历史 |
| CommentsPane.onDelete → deleteComment → engine.deleteSlideComment | 本地按来源页、authorId、idx 删除；桥真实持久化 | 逐条删除已接通，不重写同一链 |
| annotationsNonce/UndoRedo 与保存 | 本地恢复 commentEdits、同一 NativeDraft、保存映射已有 | `NATIVE_PPTX_CLASSIC_COMMENTS_ACCEPTANCE.md` 已保留先前32后端、19前端、1HTTP与冻结浏览器证据；本轮只读核对，不冒称重新运行 |
| 回复、解决、现代线程 | 固定源本专项未提供对应数据模型和操作 | 不能以新增另一根批注或删除批注冒充这些能力 |

`NATIVE_PPTX_COMMENTS_SOURCE_INVENTORY.md` 顶部已说明其“未接线”段落是早期快照，因此本轮改做实际尚未接通的公式入口。

## 公式固定源 → 本地 → 缺口关闭

| 能力 | 固定源锚点 | 修改前本地 | 本轮实现 |
| --- | --- | --- | --- |
| 真实入口 | `apps/slides/src/renderer/components/RibbonInsertTab.tsx:493–499` 的 onOpenEquation；App.tsx:1733、3450、4607 | Ribbon.insertEquation 有源 SVG/action，但 unavailable；main 无处理分支 | 保留源 SVG/action，接入新对话框 |
| 模板和自定义 | `components/InsertDialogs.tsx:210–250`；`insert-presets.ts:340–353` | 无模板／自定义输入 | `frontend/src/slides-equation.ts` 的12项源模板、中文名称、Unicode输入；模板只填值，明确插入后才改草稿 |
| 默认规格 | `insert-defaults.ts` 的 equationInsertFrame、EQUATION_FONT_PT/FAMILY/BODY_PR；`insert-actions.ts:369–396` | 已有通用 textBoxes/italic/font/geometry，但普通框为缩小文字适配 | 1英寸方框在原来源页居中，18pt Cambria Math斜体；新增 equation 布尔标识只控制 wrap none/spAutoFit，不误用艺术字段落居中 |
| 草稿／历史／保存 | 源 addElement → sessionTxn → save | 本地已有 textBoxEdits、slideChanges、restoreNativeDraft、NativeDraft、原source SHA保存链 | 复用这些结构，不建立公式外部存储或第二套历史；待保存公式文本输入即时进入草稿 |
| 协议／实际文件 | 源 addElement → pptx-engine.addElement | Python textBoxes allowlist 尚无 equation；桥无对应默认bodyPr | `report_editor/slides.py` 仅增加 allowlist/bool校验；桥TextBox校验并复用原addElement/savePptx |

所有权为新 `slides-equation.ts/.css/.test.ts`、新后端定向测试与本专项说明，及 `slides-main.ts`、`slides-native-ribbon.ts/.test.ts`、`bridge/edit-pptx.ts` 的必要局部。`slides.py` 的两处协议变化已与 root 确认。保留上述共享文件既有脏改动；未改 Word、共享AI、发布门禁、总审计、SOURCE/hash、共享 static/dist。

## TDD 与定向验证

证据根目录：`/tmp/pptx-equation-source-20261113/`。只运行定向文件，没有完整 suite 或前端构建。

- `frontend-red.log` 保留首次夹具错误：jsdom 没有 showModal；改为测试内 dialog polyfill后，`frontend-red-verified.log` 为真实 **5项失败**，均复现公式入口禁用。没有以环境错误冒充功能RED。
- `frontend-green-final.log`：最初5项宿主测试通过，覆盖12模板、明确插入、取消无草稿／焦点恢复、自定义Unicode、同一草稿UndoRedo、刷新恢复、未失焦保存请求、原source SHA与重排页映射、销毁未提交对话框。
- `frontend-related-final.log`：扩展后的公式 **7项全部通过**，新增IME确认、超限输入、保存锁定和来源页变更拒绝；该次另有1项旧Ribbon测试仍固化“公式禁用”而失败，准确保留失败记录。
- 更新该条过期契约后，`ribbon-green-final.log`：Ribbon **37项通过**。不把两次命令写成一次44项全绿，也没有重复完整suite。
- `backend-red.log`：初始 **5失败、5通过**。真实复现 Python 未允许 equation 与直调桥未拒绝伪标识；没有只测mock。
- `backend-typed-final.log`：后端 **10项通过**。测试为每次所需的 RED/GREEN 将当前桥打包到 pytest 独立临时目录，不写共享dist；真实native patch、独立python-pptx/ZIP/lxml回读、源页重排、false保持普通框、Python及桥两层拒绝非布尔标识均通过。
- `typecheck.log`：一次 `npx tsc --noEmit`，exit0。此为该时点源码检查，不外推为后续并发工作区也通过。
- 定向 `git diff --check` 通过。测试夹具曾修正将ZIP目录项当内容部件、刷新模拟未移除旧shell两项问题；没有为通过断言放宽产品行为。

## 独立真实 PPTX 回读

为避免其它并发 pytest 自动清理临时目录，真实来源与测试输出已复制到上述固定证据目录。另将当前桥独立打包到该目录 `runtime/dist/edit-pptx.mjs`，经新的 Python 进程调用真实 `patch_office`，产出 `independent-equation.pptx` 并由 ZIP/lxml、python-pptx 独立核对，结果保存在 `independent-readback.json`：

- 原两页正文为“第一张”“第二张”；输出第一页追加 `E = mc² <&> α 😀`，第二页原样保留。
- 仅 `ppt/slides/slide1.xml` 的部件字节变化，其它所有实际内容部件逐字节一致。
- 真实坐标为 x=4114800、y=2114550、cx=914400、cy=914400 EMU，对应96dpi桥坐标(432,222,96,96)。字体Cambria Math、18pt、斜体；`wrap="none"` 与 `<a:spAutoFit/>` 存在，无OMML。
- 来源SHA256：`e2e5f5890143f11fec7974de78f98777254b3d4db730649da7827f0a45cff3f0`；独立输出SHA256：`46bb90c76a902022b9a2cbc747ee41263d536b1acbefb91ba85c2ce80dd11036`；隔离桥SHA256：`01a344a6818a5405420230ab3d2072044b22d3889352f3215022947e18f0c2a2`。

以上是初始引擎文件和协议层证据；后续真实 HTTP、浏览器与冻结资产续验见下节。字体在不同客户端的实际可用性和排版不由 OOXML 字体声明证明。

## 真实 HTTP 浏览器链与冻结资产续验（2026-11-13）

可复用脚本为 `frontend/smoke/pptx-equation-smoke.mjs`、`pptx-equation-server.py`、`pptx-equation-verify.py`。真实 FastAPI 原生导入、签名 capability、授权 grant/session、CSRF、工作区、Node 桥、修订发布、下载与重开均调用应用实现；仓储复用既有 HTTP 测试的内存夹具。无浏览器 API route mock、伪造保存或业务数据库凭据。为避免导入整个 app 触发无关数据库启动，夹具直接复用 `verify_capability`、`requires_workspace_capability`、`verified_report_request` 原语。

- **源码完整链**：`/tmp/pptx-equation-browser-20261113/source-04/summary.json`。12 源模板、选模板不写草稿、取消、模板插入、自定义 Unicode、Undo/Redo、刷新恢复、聚焦输入未 blur 保存、真实修订 2 授权下载、原件身份不变、打开新修订并按真实对象 ID 回读全部通过。实际加载 104 个源码 JS/TS 响应；页面、console、HTTP 错误均为空。来源 SHA 为 `865127a8d01b31cff4380cd0c89ce5f808ec2073eaaefb385bfed8cb757b4f1a`，实际下载 SHA 为 `a9aca9ef184438d6a23527b2e144bb20f04b15eaac4ad7df5d4441890ea91e91`。独立 ZIP/python-pptx 核对仅 slide1.xml 内容变化，两个文本框为 Cambria Math、18pt、斜体、wrap none/spAutoFit，原正文、讲稿、第二页及其余内容部件保留。
- **截图时序定位**：源码链最早的重开截图早于 Konva 稳定绘制，不能据其空白声明画布验收通过。`source-visual-only-01` 只重新导入同一真实下载产物做只读打开，没有保存；等待 `document.fonts.ready` 和两个 rAF 后，画布有 6865 非白像素且正文和公式可见。通用脚本已加入同样等待与像素断言。两个公式沿用固定源同一默认中心坐标，因此本夹具显示重叠，未改变应用布局行为。
- **冻结 87a8… 最小续验**：`frozen-87a8aff4-01/summary.json`，manifest `87a8aff45cc2cb8593f2525615895f505fb6721950ff27f5a56de5d034f9efbb`。CDP 禁用缓存、禁用 service worker，131 个实际 JS 资源逐项与冻结文件 SHA 匹配；对上述真实下载产物重新导入并授权读取、预览，12 模板入口与取消无写入通过。稳定画布非白像素 5771、公式区域 3344，`reopened-stable.png` 已目视检查。该续验没有 HTTP save；原始新修订重开与保存链仍由 source-04 的完整链证明，不能把重新导入误称为又一次修订 2 重开。源发布 validation 继续为 `ok:false`、`native_source_review_pending`，未把业务与完整版式验收标为通过。
- **冻结桥最小重放**：`frozen-equation-replay-01/equivalence.json`。对源码链同一真实保存 payload 使用冻结应用桥重放，再由独立 ZIP/lxml/python-pptx 验证。47 个内容文件中，除 slide1.xml 外全部逐字节相同；slide1.xml 只存在两个新增文本框 `a16:creationId` 随机 UUID 差异，明确仅归一化这两个值后 canonical XML 完全一致，未归一化其他属性。冻结重放输出 SHA 为 `11a747ee9b3d2fbe721187c7e5e3ed343e1091df2648c7c142ae65002c9a933f`。没有重复 HTTP 保存。

所有证据均位于固定目录 `/tmp/pptx-equation-browser-20261113/`，不依赖 pytest 自动清理目录。`source-01`/`source-02` 保留夹具启动阶段不应导入完整 app 的失败，`source-03` 保留末端误用对象显示 label 的选择器失败和已真实下载的产物，未用这些失败回合冒充全绿。脚本参数为 `PPTX_EQUATION_DIRECTORY`、`PPTX_EQUATION_SOURCE=1`、`NATIVE_EDITOR_ASSET_ROOT`、`PPTX_EQUATION_ENGINE_ROOT`、`PPTX_EXPECTED_MANIFEST_SHA256`；设置 `PPTX_EQUATION_REOPEN_FILE` 启用最小只读续验。最终统一构建若因 Word 独立修改更换 manifest，须追加实际 PPTX 依赖身份映射，不能沿用 87a8… 为新包背书。

### 最终 68ce… 包：依赖映射及并发变化边界

最终 manifest 为 `68ce99975149470621d980fcf040694372b986a4c037e5463f07d85a8edf67e2`。对照根节点保全的 `/dev/shm/office-source-entry-87a8-static`，上一轮实际加载的131脚本中，93项原字节一致、36项只需精确归一化已映射的引号内 JS/CSS 资源文件名。剩余两项不能笼统称为“仅引用变化”：

1. `native-docx-engine` 的实现前缀原字节相同，末尾10个 export alias 重排，局部绑定集合相同；逐项解析131消费者后，没有消费者使用这10个受影响 export，`slides-main` 对它是副作用导入。
2. `slides-main` 有两处**并发源变化，非本专项公式变更**：Ribbon tab keydown 新增 defaultPrevented/isComposing/keyCode229 防护及可见可用标签过滤；setContext 隐藏原上下文标签时恢复焦点。这些变化由其他会话产生，root 未授权或实现，保留而未覆盖；不能声称本次 PPTX 代码全部未变。除明确排除这两个 block 外，使用 TypeScript 词法符号解析比较2541个绑定，保留属性名、全局名、import/export 名、字面量与操作符，剩余代码等价；不是无条件删除全部 Identifier 名做比较。

`/tmp/pptx-equation-browser-20261113/final-68ce9997-identity/` 保留 `comparison.json`、`ast-differences.json`、`binding-equivalence.json`、`semantic-boundary.json` 及 `final-acceptance.json`。其中初次 esbuild 直接重压缩结果字符串不相同（见 semantic-boundary），最终 binding-equivalence 才是范围明确的词法比较证据，未将前者冒称相等。

必要的最终冻结只读续验见 `final-68ce9997-browser-02/summary.json`：CDP禁缓存，131个实际JS响应逐SHA匹配最终资产；同一真实下载产物重新导入/授权/读取/预览、12公式模板与取消不写入、稳定画布可见性检查通过（不含无重叠/可读排版验收）。画布非白5771、公式区域3344像素，截图已目视核查。并发Ribbon的IME/229/defaultPrevented防护、End/ArrowRight在实际可见标签间循环、实际对象checkbox多选让context隐藏并恢复home焦点均通过，无页面/console/HTTP错误，无HTTP保存。`browser-01`保留首个夹具用canvas清选择造成焦点先按既有逻辑进入canvas的失败；它没有满足“焦点仍在上下文标签”前提，随后改用真实对象多选change链核验恢复分支，未修改产品代码。

最终与87a…的 edit/render 桥SHA完全相同，因此前述冻结桥最小重放及独立ZIP回读仍适用。源码完整保存/修订2重开、冻结只读续验与并发变化检查分别分层记录，不代表整个并发worktree做过统一全量验证。验证结果仍保留 `ok:false/native_source_review_pending`，没有改成业务验收通过。最终脚本快照与SHA位于 `final-68ce9997-browser-02/driver` 和 `script-identities.json`；设置 `PPTX_EQUATION_RIBBON_CHECKS=1` 可启用本次只读键盘补验。

### 公式重叠与视觉证据的准确边界

最终 `reopened-stable.png` 中，`E = mc²` 与 `未失焦 α = 42 <&> 😀` 两个文本框明显叠放，**没有通过“无重叠”或“清晰可读排版”验收**。这是本夹具在同一来源页先插模板、再插自定义公式，且两次都不移动默认插入框的预期结果；不是新增的自动避让或布局能力。固定源 `insert-defaults.ts:40` 的 `equationInsertFrame(slide)` 每次都返回居中的1英寸方框，`insert-actions.ts:369–396` 每次直接使用该 frame，未按已有对象偏移或做碰撞检测。本地 `equationTextBox` 与下载后独立回读都给出相同坐标 `(4114800, 2971800, 914400, 914400)` EMU，所以连续插入的两个对象必然同位叠放。

5771个画布非白像素、3344个公式区域像素及人工截图检查，仅证实异步画布完成绘制、已保存的对象可见，排除了之前截图过早的空白；**可见性像素不等于可读排版、无重叠、数学排版质量或OMML质量**。固定源与本地的此功能均为Unicode数学字体文本框，没有OMML结构，也没有数学语义布局质量声明。本次不修改产品默认插入位置、不新增自动避让、不重跑HTTP保存；业务/完整版式核验继续保留 `ok:false/native_source_review_pending`。

## 明确保留边界

- 固定源的公式即Unicode数学文本框；本轮没有新增OMML、数学语义计算、LaTeX或结构化公式编辑器。
- 已保存对象沿用普通文本框的读取／文本编辑；没有“识别任意来源公式并重新打开模板”的能力声明。
- 复用现有通用待保存清单。草稿中公式在保存新修订后才显示在画布上，与现有新增文本、艺术字一致；未宣称源桌面的即刻Canvas编辑已完整移植。
- 当前可写来源页可插入；尚未保存的新建／复制页仍受既有统一边界约束，不借此放开其它未核验来源操作。
- 没有修改下载签发步骤或验收门禁，不改变验证失败仍签发已核验产物的契约。
- 未共享构建、未覆盖static/dist、未完整回归、未提交、推送或部署；不代表PPTX或四格式全面对齐。
