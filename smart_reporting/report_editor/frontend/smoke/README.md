# Report Editor 生产冒烟

以下生产检查必须使用真实 reporting 后端和有效编辑会话。Vite API fixture 只能验证前端渲染，不能替代权限、会话和 renderer 链路。

## 自动化检查

在已安装 Playwright 的环境中，将浏览器已有的有效会话地址传入脚本；脚本只读页面，不会触发保存或导出：

```bash
REPORT_EDITOR_URL='https://reporting.example/reports/v1/editor/<report>/<revision>' \
REPORT_EDITOR_BROWSER=chromium \
npm run smoke
```

将 `REPORT_EDITOR_BROWSER` 改为 `firefox` 可执行 Firefox 检查；`HEADLESS=0` 可显示浏览器窗口。

默认脚本严格只读。仅可废弃的测试报告允许执行完整链路：

```bash
REPORT_EDITOR_URL='https://reporting.example/reports/v1/editor/<report>/<revision>' \
REPORT_EDITOR_ALLOW_MUTATION=1 \
REPORT_EDITOR_BROWSER=chromium \
npm run smoke
```

写入模式依次执行：保存唯一探针、使用旧 SHA 验证 409、恢复原 Markdown、导出一个新 revision，并下载检查 PDF `%PDF-` 与 Word `PK` 文件头及文件大小。即使正文恢复，导出仍会创建新 revision；禁止用于用户正式报告。

## 桌面端

1. 从报告列表打开编辑器，确认 Markdown 正文、目录和保存时间正常显示。
2. 修改一段正文，确认状态依次为“有未保存更改”“保存中”“已保存”。刷新页面后内容仍存在。
3. 在两个窗口编辑同一 revision，确认后保存的窗口收到 409，并可选择本地、远端或合并后重试。
4. 使用过期会话打开页面，确认显示 410 会话过期面板，不出现空白编辑区。
5. 分别导出 PDF 和 Word，确认状态显示准备、生成、完成，下载链接可访问，失败时可以重试。
6. 抽查封面、目录、页眉页脚、页码、中文字体、宽表格和跨页图片。
7. 导出失败时记录页面显示的请求编号，并确认服务端 `report_editor_export_failed` 日志包含相同 `request_id`、report、revision、耗时和错误码。

## 移动端

1. 在 375px 和 768px 视口确认底部 6 个主操作保持单行，更多菜单不会超出屏幕。
2. 唤起软键盘后编辑当前段落，确认光标和底部工具栏可见，页面没有横向整体滚动。
3. 打开目录、历史、导出设置和冲突弹窗，验证 Tab/Shift+Tab、Esc 和关闭后的焦点回收。

## 浏览器矩阵

- Chromium：当前稳定版。
- Firefox：当前稳定版，重点检查 sticky 目录、fixed 移动工具栏、宽表格滚动和 Milkdown 浮动工具栏。
- Safari/iOS：发布前使用真机验证 safe-area 与软键盘；桌面模拟不计为真机证据。

## v6 证据浏览器 fixture 定向回放

3D 相机工具回放检查定位、放大、缩小和重置后预览/标题/历史不变，定位画布截图为 `output/report-editor-v6-3d-locate.png`；截图检查范围为当前节点居中，不代表邻居与长标签全部落入视口。

3D 回放还检查节点选择与关闭后的选择器焦点、Escape 关闭预览和 Enter 导航；相机恢复的对照画布截图为 `output/report-editor-v6-3d-camera-{before,preview}.png`。截图提供指定三节点的视觉证据，不是全部图和全部动画时刻的坐标断言。

默认 3D 挂载与容器尺寸回放：构建后启动 `node smoke/fixture-server.mjs`，运行 `node smoke/evidence-3d-fixture.mjs`。使用真实 Chromium WebGL，核对 1280px/390px 画布与容器尺寸、无整页横向溢出、2D/3D 往返及无脚本异常；通过原生节点选择器核对预览不改历史、390px 操作按钮完整可见、分支加载失败/重试、关闭、进入与后退恢复。截图为 `output/report-editor-v6-3d-{1280,390}.png` 与 `output/report-editor-v6-3d-preview-390.png`。此用例不覆盖画布鼠标命中、全部键盘流程、实例资源释放或复杂图可读性，不能用 2D fixture 的结果替代这些 3D 验收项。

3D 追踪回放新增原生端点固定/取消、适应两端、分支加载后的端点更新、关系计数与无预览禁用检查，保持预览身份/标题/历史；390px 控件不越界且画布高于100px。截图为 `output/report-editor-v6-3d-trace-390.png` 和 `output/report-editor-v6-3d-trace-branches.png`，需人工核对突出连线与背景边。关系计数断言本身不能证明渲染正确；小图截图仍存在标签重叠，不作为复杂图可读性证据。

同一3D回放还通过真实鼠标扫描球体，以组件悬停输出的 `data-hovered` 身份确认命中，再验证悬停关系计数、画布单击预览且不导航、双击进入与后退恢复。未调用组件回调或直接修改图实例。3D单击有350ms双击判定等待；双击回放使用两次间隔100ms的点击。此检查不覆盖中键、修饰键、右键或触控手势。

鼠标旋转/缩放回放从画布空白处拖动并滚轮放大，检查画面变化和随后节点命中/预览/双击导航；截图为 `output/report-editor-v6-3d-{rotated,wheel}.png`。相机偏好回放在运行中切换 `reduce` 与 `no-preference`，检查定位、放大、缩小、重置、适应五个动作：分别等40ms/240ms截图，再等300ms截图要求完全一致，并保持预览/标题/历史。该画面稳定性证据不证明动画进行中切换偏好、触控或任意复杂图。

复杂3D回放：同一fixture服务运行 `node smoke/evidence-complex-3d-fixture.mjs`。沿用2D复杂图的共享输入、反馈环、自引用及多批次追加，检查39个累计节点、切到2D后的55条登记边、1280×900/390×844/844×390布局、固定/取消追踪、预览/历史保持与进入/后退恢复。固定追踪通过组件可见性过滤仅显示两端与对应关系，取消恢复全图；自引用不列为独立端点选项。截图为 `output/report-editor-v6-complex-3d-{1280,390,844}.png` 与 `output/report-editor-v6-complex-3d-trace-{1280,390,844}.png`。自动断言不作为整体可读性判定；需人工检查自引用环、追踪边和名称，当前完整图名称仍偏小、远端标签受透视缩小。结果不替代真实后端权限/索引、规模性能、触控或读屏证据。

追踪文字现使用组件固定屏幕尺寸能力，目标12px；取消追踪恢复原比例。复杂3D回放在每种视口追踪时缩小后截图 `output/report-editor-v6-complex-3d-trace-zoom-{1280,390,844}.png`，再放大检查端点选择与追踪关系保持。需人工对照原追踪截图确认远端名称可读、缩小时文字大小保持。指定first-0/shared-0已检查，不代表长名称、任意旋转角度或全图概览验收通过。

长名称变体运行 `REPORT_EDITOR_LONG_LABELS=1 node smoke/evidence-complex-3d-fixture.mjs`，两端改为超长中文名称，关系形态与39/55规模不变；截图文件名追加 `-long`。验证选择器与预览摘要保留全名，追踪时类型/状态和最多14字的名称分两行。普通与长名称变体均在适应/缩小后读取真实截图像素，四边内缩2px要求为背景，失败报告像素位置与RGBA；该检查排除主题边框/截图舍入，不能代替标签间遮挡和整体可读性的人工检查。

详情回放也验证空快照与筛选零匹配使用不同提示；点击“清除筛选”恢复本页行、隐藏空态，并把焦点返回搜索框。空态在表格之外，不计入复制行。

详情视觉与操作区回放：构建后运行 `node smoke/evidence-detail-style-fixture.mjs`，支持 `REPORT_EDITOR_URL` 指向隔离fixture服务。以固定响应覆盖1280px/390px的事实软告警、长计算参数、快照、零匹配、分页失败/恢复、下载拒绝、元数据与分页均为0行的固定快照、加载与详情失败。检查整页/工作区无横向溢出、失败保留当前表格并可重试、反馈具有status语义、白色内容底、表格贴合列宽、窄屏操作按钮尺寸、无脚本错误；截图为 `output/report-editor-v6-detail-<场景>-<宽度>.png`。不使用正式报告，不替代真实业务登记、授权或真机证据。

在 frontend 目录完成构建后，用一个终端启动 `node smoke/fixture-server.mjs`（默认端口 4173），另一个终端运行：

```bash
node smoke/evidence-navigation-fixture.mjs
```

该回放支持 `REPORT_EDITOR_URL` 指定 fixture 服务地址；脚本中的保存校验请求会从同一地址派生，便于使用非 4173 临时端口。

此脚本仅针对固定 fixture，检查任务内图累计、已有节点坐标与跨任务隔离、图滚动恢复、快照分页及筛选/列宽/表格滚动在后退和刷新后的恢复、完整路径、折叠祖先导航与历史恢复、任务列表 Esc、390px 独立图视图、缩放后预览、关闭预览和返回详情的焦点，以及隐藏标签和整页溢出。还在浏览器中模拟保存失败，检查未保存正文、选区和窗口滚动在切回正文后保留；该步骤只改 fixture 浏览器草稿，不写正式报告。截图保存到项目 `output/report-editor-v6-mobile-{path,graph}.png`。这些结果不能代替上述真实后端生产检查。


草稿引用校验缓存的独立回放使用同一 fixture 服务：

```bash
node smoke/evidence-validation-fixture.mjs
```

脚本模拟保存失败，并在真实编辑器中修改引用数值，验证已缓存事实页与引用页按新草稿重新校验、登记事实详情继续复用；确认 fixture 文档未被保存。该回放不覆盖真实后端校验、权限或跨修订服务链路。

fixture 的 `/api/sources/validate` 会校验请求正文的 SHA-256，不接受保存基准摘要。需要使用另一端口的 fixture 服务时，可传入 `REPORT_EDITOR_URL`，例如 `http://127.0.0.1:4174/reports/v1/editor/fixture-report/1`。

真实后端的 `cached_evidence` 用例也支持 `REPORT_EDITOR_BROWSER=firefox` 或 `webkit`。增强用例在三个引擎各通过 1 项，检查键盘改值、未保存文字与选区在证据切换后保留、缓存校验软告警、真实保存及登记事实只请求一次；不替代修订恢复后连续编辑或真机软键盘验收。

`history_restore_reverts` 用例也支持引擎选择，三个引擎各通过 1 项：恢复旧正文/来源后编辑可见标题，证据切换保留新选区，真实保存及刷新后编辑文字和历史 CSV 均保留。该用例没有恢复前已打开的证据任务，不证明旧任务清空；不替代真机或全流程矩阵。

后续增强已登记恢复前修订的真实来源，先创建带筛选的快照任务和已关闭引用任务，再确认恢复后任务数归零、关闭记录不可恢复、新快照筛选为空。增强用例在三个引擎各通过 1 项，补齐旧任务清空证据，不覆盖全部迟到请求竞态。

共享依赖用例已参数化为 `small`（12 叶子）与 `scale`（100 叶子），仅运行新增规模可使用 `-k 'shared_fact_dependencies and scale'`。103 节点/202 边的两批真实加载在三个引擎各通过 1 项，打印每批请求至渲染完成的观察耗时。结果只覆盖该规模与共享叶子形态，不是任意图或全规模性能保证。

复制内容回读使用 fixture 服务：`node smoke/evidence-copy-fixture.mjs`，可通过 `REPORT_EDITOR_URL` 指定地址、`REPORT_EDITOR_BROWSER=firefox|webkit` 选择引擎。Chromium 使用预授予权限的 Clipboard API 回读；Firefox/Linux WebKit 不预授权，通过真实 Control+V 粘贴到临时 textarea，核对整页、筛选后、零匹配及第二页与可见表格一致。`REPORT_EDITOR_CLIPBOARD_DENIED=1` 给文档响应加 `Permissions-Policy: clipboard-write=()`，不替换 Clipboard API；Chromium 已验证四次复制均提示不可用、按钮保持可用且不误报成功。拒绝模式明确要求拒绝，成功模式明确要求回读，不能混用通过结论。不替代各引擎权限弹窗、外部应用粘贴或真机验收。

正文定位检查：`node smoke/evidence-motion-fixture.mjs`，同样支持 `REPORT_EDITOR_URL`。核对 reduce 使用 auto、默认使用 smooth，以及编辑器持续焦点、直接输入、高亮超时清除和撤销。保存失败响应隔离测试编辑，不修改 fixture 保存稿；截图为 `output/report-editor-v6-locate-highlight.png`。仅覆盖指定文本引用，不替代所有类型或真机验收。

定位回放也支持 `REPORT_EDITOR_BROWSER=chromium|firefox|webkit`。指定文本引用在三个引擎各自的两种媒体偏好下通过；非 Chromium 截图分别为 `output/report-editor-v6-{firefox,webkit}-locate-highlight.png`，不覆盖原 Chromium 截图。Node 引擎版本和 Linux WebKit 运行库要求同键盘回放。

详情导航检查：`node smoke/evidence-detail-links-fixture.mjs`，支持 `REPORT_EDITOR_URL`。使用实际鼠标输入，检查引用页事实/计算、事实输入、计算输出四类链接的 Ctrl 后台打开、中键复用、Ctrl+Shift 前台激活、普通点击当前任务导航与后退。可用 `REPORT_EDITOR_LINK_CASES=input,output` 只运行新增输入/输出场景。事实输入由回放注入固定叶子依赖，证据不替代真实依赖解析、授权或完整浏览器矩阵。

正式前端键盘回放：`node smoke/evidence-keyboard-fixture.mjs`，支持 `REPORT_EDITOR_URL`。检查手动页签激活与请求数、Home/End/Delete、图节点 Space/Enter/Esc、关闭预览焦点恢复、路径 aria-current 及返回正文编辑器焦点。固定数据流程不替代真实授权或屏幕阅读器验收。

键盘回放现支持 `REPORT_EDITOR_BROWSER=chromium|firefox|webkit`，默认 Chromium，明确选择的引擎缺少执行文件或依赖时失败。指定流程三个引擎均有通过记录；Node Playwright 使用 Firefox build 1490 与 WebKit 26.0 build 2203，与 Python Playwright 矩阵版本不同。Linux WebKit 须安装运行依赖（含 libwoff1），不替代 Safari/iOS 或屏幕阅读器验收。

同事实多引用身份的真实后端测试（项目根目录）：`.venv/bin/python -m pytest -q -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k same_fact_subject_tasks`。支持现有 `REPORT_EDITOR_BROWSER` 选择三个引擎，Linux WebKit 仍要求运行库。先交换授权，再访问编辑器 `?subject=`，授权交换地址自身不保留该查询参数。测试真实登记两条同事实/同显示名引用，核对任务身份与独立历史，不断言合成口径已业务核对。

触控输入模拟使用 fixture 服务，在 frontend 目录运行：

```bash
node smoke/evidence-touch-fixture.mjs
```

可用 `REPORT_EDITOR_URL` 指定地址。Chromium CDP 触摸输入检查单指平移、双指间距缩放、松开一指后续拖、节点起始捏合、捏合后鼠标点击、缩放后轻触预览/关闭及无整页溢出。截图保存为 `output/report-editor-v6-touch-emulation.png`。这只是浏览器触控模拟，不替代移动真机或软键盘验收。

真实后端的 v6 定向回放在项目根目录运行（需要已构建前端、Python Playwright 与系统 Chromium）：

```bash
.venv/bin/python -m pytest -q -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k 'retired_sources or online_subject or loads_table or history_restore'
.venv/bin/python -m pytest -q -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k cached_evidence
.venv/bin/python -m pytest -q -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k snapshot_download_and_access_failures
.venv/bin/python -m pytest -q -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k large_snapshot_pagination
.venv/bin/python -m pytest -q -s -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k high_fanout_graph
```

这些回放创建临时工作区和本地 HTTP 服务，使用真实授权、来源索引及文件，不连接生产报告；缓存草稿用例会改写并保存临时报告。覆盖来源过期/有效修订、会话过期、CSV 预览、正文/图片恢复和缓存事实的草稿校验。桌面 Chromium 结果不替代移动真机验收。

下载与访问异常回放覆盖拥有者正常下载（文件名及完整字节）、分享拒绝、预览前及预览后文件完整性失败，并检查 390px 布局、返回正文和无异常下载。`HEAD` 探测与 `GET` 下载均走真实授权和完整性校验。Snap Chromium 的下载使用项目内独立临时目录，在 fixture 结束时清理；报告数据仍位于 pytest 临时工作区。

该四场景回放支持 `REPORT_EDITOR_BROWSER=firefox` 或 `webkit`。Firefox 四项通过，WebKit 拒绝场景三项通过；WebKit 正常下载曾导航为 CSV，已改用成功 HEAD 后的同源下载链接，修复后三个引擎各重跑正常下载通过，中文文件名与全部字节一致。Linux WebKit 不替代 Safari/iOS 真机下载证据。

大文件回放登记约 30 MiB、20,000 行合成 CSV，验证每页 50 行、第二页筛选与列宽刷新恢复、连续失效游标错误只提供一个恢复动作、当前数据保留、分页及刷新时过期后回到第一页。仅推进 CSV 游标服务的测试时钟触发真实签名游标过期，不改变会话时钟或伪造 HTTP 响应。390px 回放检查错误提示在分页按钮下方和整页无横向溢出；不属于最大文件或性能上限验收。

高扇出回放通过真实索引与接口提供同一事实的 300 个引用，检查 301 节点/300 边、无节点重叠、末端可进入、预览及后退坐标稳定、390px 缩放后点击与返回焦点。打印单次加载/预览耗时供观察，不定义性能承诺；长画布访问结果不替代复杂图或真机体验验收。

该回放同时检查“定位当前对象”：当前节点完整进入图视口并聚焦，原末端预览及坐标保持；“重置视图”恢复图滚动原点。独立移动图视图中的定位截图由 pytest 保存为 `high-fanout-current-mobile.png`。

大文件与高扇出两项用例也支持 Firefox/WebKit（其他用例仍使用系统 Chromium）。先安装与 Python Playwright 匹配的浏览器，WebKit 还需要主机运行库：

```bash
.venv/bin/python -m playwright install firefox webkit
REPORT_EDITOR_BROWSER=firefox .venv/bin/python -m pytest -q -s -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k 'high_fanout_graph or large_snapshot_pagination'
REPORT_EDITOR_BROWSER=webkit .venv/bin/python -m pytest -q -s -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k 'high_fanout_graph or large_snapshot_pagination'
```

上述命令在项目根目录运行。明确选择的 Firefox/WebKit 缺失时测试失败，不因没有系统 Chromium 而跳过。2026-10-01 使用 Python Playwright 1.63.0、Firefox 155.0 与 Linux WebKit 26.6 各通过这两项；WebKit 主机缺库在本次验证中用临时解压的 Ubuntu 库和进程级预加载解决，未改系统安装。常规运行环境可按 `playwright install-deps webkit` 提示安装依赖。此证据不覆盖所有编辑器流程，不替代 Safari/iOS 真机验收。


图表作图数据分页的独立回放也使用同一 fixture 服务：

```bash
node smoke/evidence-chart-fixture.mjs
```

脚本通过浏览器路由提供两份不同长度的固定作图数据，验证当前页替换、失败重试、进入计算后后退恢复、刷新按偏移量重新加载和上一页。只使用固定数据，不覆盖真实图表文件完整性校验。


节点分支加载回放使用同一 fixture 服务：

```bash
node smoke/evidence-branch-fixture.mjs
```

验证分支失败、重试及加载中提示、追加关系后保留节点坐标和导航历史、收起后展开保留、390px 图视图无整页溢出。桌面和移动截图保存到项目 `output/report-editor-v6-branch{,-mobile}.png`。固定 fixture 无法替代真实后端授权与大图验证。

可设置 `REPORT_EDITOR_URL` 指向隔离 fixture 服务。使用 `REPORT_EDITOR_LONG_PREVIEW=1` 增加长计算名称，检查未选择、预览、失败、加载、完成五种状态下的1280px/390px布局：摘要完整、按钮无重叠且完整可见、移动画布高度稳定、关闭后焦点回收。此模式仅改浏览器固定响应中的计算身份，不替代真实业务登记；截图保存为 `output/report-editor-v6-preview-{empty,selected,error,loading,loaded}-{1280,390}.png`。

任务关闭后恢复的独立回放使用同一 fixture 服务：

```bash
node smoke/evidence-restore-fixture.mjs
```

验证 1280px 和 390px 下通过“全部任务”恢复最近关闭的任务，保留筛选词与匹配数；实际拖动页签后刷新，检查任务顺序与当前页筛选恢复；检查窄屏关系计数宽度和整页溢出。截图保存为项目 `output/report-editor-v6-restore-mobile.png`。恢复记录仅在当前浏览器实例内保留，刷新和修订重置后清空；打开任务的原会话恢复策略不变。

复杂关系和多批次增长回放也使用同一 fixture 服务：

固定端点后也实际点击“适应追踪关系”，检查两端节点屏幕边界和每4px采样的SVG路径均在390px画布内，原节点坐标与预览身份不变；长距离缩小后文字的可读性仍需截图审查，几何检查不能替代完整视觉验收。

复杂图回放包含预览端点选择：选中端点只追踪与预览节点之间的登记边，返回全部关系恢复原样；验证390px控件宽度/40px高度、原生方向键选择与恢复，以及坐标和预览身份不变。截图 `output/report-editor-v6-graph-trace-picker-mobile.png`；此窄屏浏览器回放不是手机原生选择器或触摸真机证据。

```bash
node smoke/evidence-complex-graph-fixture.mjs
```

可用 `REPORT_EDITOR_URL` 指定另一个 fixture 地址。浏览器路由提供四批固定事实关系，含共享输入、反馈环、自引用，共 39 节点/55 边。检查每批既有坐标稳定、节点去重与无重叠、连线不穿过非端点节点、进入后退恢复、390px 缩放与末端预览及当前对象定位。穿线检查沿 SVG 路径每 4px 采样，不能证明任意图或全部几何边界。截图为 `output/report-editor-v6-complex-graph{,-mobile}.png`。固定响应不提供真实后端、复杂图性能上限或真机证据；避障后仍有共用通道的边，可读性需继续验收。

回放也验证临时关系追踪：悬停预览对象的相邻节点突出1条关系，原生聚焦另一个相邻节点突出2条双向关系；实际检查其他边淡化、追踪边上层顺序、标题/预览/坐标保持。先滚动关系容器再悬停，截图后再次确认追踪身份。截图为 `output/report-editor-v6-graph-trace-{hover,focus}.png`；不把鼠标回放推广为移动触控追踪验收。

此回放还检查预览节点的直接关系突出、其他边淡化与绘制顺序：分支预览为 3 条突出/52 条淡化，窄屏另一预览为 1 条突出，定位当前对象后保持该选择。该检查不证明全图概览或所有共用通道关系的可读性。

真实共享依赖回放在项目根目录运行：

```bash
.venv/bin/python -m pytest -q -s -m integration smart_reporting/reporting/tests/test_report_editor_browser.py -k shared_fact_dependencies
```

可通过 `REPORT_EDITOR_BROWSER=firefox` 或 `webkit` 切换引擎。真实文件/索引/manifest 登记两个派生事实与 12 个共享叶子，分批展开为 15 节点/26 边；检查坐标、历史、节点去重/重叠、实际连线穿线、预览关系突出与390px 布局。2026-10-01 三个引擎各通过 1 项。该用例不伪造 HTTP 响应，不证明任意事实环、业务口径有效、规模性能或真机体验。
