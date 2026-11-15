# Three 分块运行时专项

2026-11-13。只验证 PPTX 模型插入时的真实 Three／GLTFLoader／WebGL 运行与草稿登记，不代替模型保存、重开、旋转、编辑和完整生命周期验收。

## 失败与根因证据

旧冻结构建 `static-lifecycle` 的体积预算通过，但实际 GLB 插入在 `await import('three')` 后显示 `Cannot access 'gs' before initialization`，没有登记模型草稿。旧目录分包使场景、基础数学、core、extras、renderer 分块互相依赖。加载6份Three资源后失败，未进入loader。产品捕获异常并显示状态，所以页面／控制台错误数组为空不能证明运行通过。

失败目录 `/tmp/office-model3d-runtime-20261113` 和日志 `/tmp/pptx-model3d-runtime-browser-20261113.log` 已完整保留于持久归档 `office-parity-review-print-20261113/model3d-runtime-red/`，截图已目视检查。

## 当前冻结运行结果

当前工作树配置使用固定 Three `0.186.1` 的模块分组表 `frontend/scripts/three-chunks.json`。root 独立检查391份源码模块的跨组相对导入均指向较早组；隔离产物14个Three分块的静态依赖图无环。这里记录的是当前磁盘配置的验证，不认领其它并发会话的实现。

- 冻结静态目录 `/tmp/office-three-runtime-20261113/static`，manifest SHA256 `3e7b76390cfdc0d9fe924fff463be507939d3602b584216973af5e05da8ca343`。
- 脚本 `frontend/smoke/pptx-model3d-runtime-smoke.mjs`，输出 `/tmp/office-model3d-runtime-20261113-green`，日志 `/tmp/pptx-model3d-runtime-browser-20261113-green.log`。
- 真实 HTTP 夹具使用现有工作区授权／原生导入／PPTX bridge；实际模型有顶点、索引及红色材质，不使用缺乏几何数据的协议夹具代替绘制。
- 真实 Chromium 请求 SwiftShader 后端；没有把请求参数当作测得的硬件身份。14个Three分块实际加载，178份应用资源响应逐文件与冻结磁盘SHA匹配。
- GLB SHA256 `6f1f7d698c42aa7703b950b959eb3d30527c35abe19b699f0eac7b625598ae1c`；生成PNG SHA256 `03b342f9b491faf73e2fdf3c976fbac4d9c23e15cc74cdbb49c9777b598ed4e2`。
- Python/Pillow独立回读PNG为720×720、111390个红色／非透明像素，边界框 `(125,125,595,596)`；目视为红色三角形。模型草稿保留原GLB身份、默认旋转和PNG。
- 无保存、新修订0；页面、控制台、HTTP错误数组均为空。该结论不证明生产HTTP鉴权或桌面PowerPoint一致性。

本次构建Vite exit 0，但现有预算检查仍有两个其它分块失败：Word render 710.7 KiB 超过710、Workbook main 378.8 KiB 超过253。未提高预算；不得把本运行专项成功当成整体验收通过。

## 体积收敛后续验

审计 `module-audit.json` 后，将共享Fluent图标、图表面板控件、纯数据字体度量表放入独立且现有依赖方向一致的边界，未改业务逻辑或预算限额。新的隔离输出 `/tmp/office-parity-convergence-20261113/static` Vite exit 0（52.12秒），manifest SHA256 `404da158e5e37f9f91eb72244369e8c3dcb791642d7e29096ee6b3c66a00141b`；现有预算检查0失败。Word render686441、字体度量231109、Workbook main256109、共享图标113470、图表控件17850 bytes。TypeScript `--noEmit --pretty false` exit 0，日志 `/tmp/office-parity-convergence-tsc-20261113.log`。

14份Three分块与上个通过运行的冻结构建逐SHA相同。仍在最新冻结资源上运行增强后的同一浏览器专项：`/tmp/office-parity-convergence-20261113/model3d-browser/summary.json` 为 `ok=true`、178份应用资源身份匹配、14份Three实际加载；浏览器自己解码PNG并统计111390个红色像素，不只验证PNG文件头。日志 `/tmp/office-parity-convergence-model3d-20261113.log`。这完成了3D插入的本次分块回归，不扩大其它格式或保存生命周期的结论。
