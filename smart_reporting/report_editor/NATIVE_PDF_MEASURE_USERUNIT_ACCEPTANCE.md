# PDF 跨 UserUnit 页面测量标定

2026-11-12，基于PR #218。固定GenOffice源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 原始依据与问题

原源 `apps/pdf/src/renderer/App.tsx` 的测量提交及标定回调使用原始端点的Math.hypot，再交给measure.ts的parseCalibration/formatLength；本地沿用了这个计算。PDF.js的PDFPageProxy.userUnit声明为“默认用户单位以1/72英寸计的大小”，page.view则为原始用户坐标。由此一条100用户单位的线在UserUnit2页占200物理pt，在UserUnit1页占100物理pt；直接跨页复用原始坐标标定会混淆这两种长度。

旧冻结构建真实UI先红：同一两页来源在第一页UserUnit2画80用户单位并标为2m，切到UserUnit1页画80用户单位，旧实现得到2.00m，应为1.00m。首条校准成功、原始端点均[110,240]→[190,240]，不是鼠标比例或页面缩放造成；失败证据目录 `/tmp/pdf-measure-userunit-browser-20261112-red`。该问题在固定源也存在，因此本批是本地物理一致性适配，不宣称新增上游原本缺少的工具。

## 实现

复用原parseCalibration/formatLength，不改vendored源。pdfLineLength增加可选userUnit（默认1兼容既有调用），用原始端点长度×UserUnit计算物理pt；pdfMeasurementOperation按同一规则生成标签，原始坐标、页面身份和操作协议不变，不保存额外userUnit字段。

pdf-main在绘制时使用该来源PDFPageProxy.userUnit；标定弹窗冻结目标页面单位，保留原文档/草稿快照检查，标定提示及会话比例显示物理pt。之后每页的测量均使用该页实际单位；重新标定仅影响后续标签，原有操作和已保存文件的标签不重写。非法、非正或导致长度溢出的单位拒绝生成错误标签。

## 定向验证

新增9项先红（既有3项通过）；修复后pdf-measure12项与pdf-object-host12项共24项通过。包括2→1、2→2、1→2、相同物理长度、原始坐标保持、默认Unit1兼容、无效单位及数值溢出。日志 `/tmp/pdf-measure-userunit-red.log` / `-green.log`。

完整npm run build（Node heap4GiB，包含tsc）通过，Vite43.48秒；全部JS预算通过，不放宽阈值。日志 `/tmp/pdf-measure-userunit-build.log`、`/tmp/pdf-measure-userunit-budget.log`。只跑受影响定向验证，未重复全项目测试。

## 真实浏览器与独立文件核对

新增专属smoke/server/verifier，服务端复用已有source注入入口与真实路由/授权/workspace/Node writer/publication；修订持久化使用隔离有作用域内存仓储。实际两页均MediaBox `[0,0,500,600]`、CropBox `[30,40,430,440]`，UserUnit依次2/1，分别含UNIT2 CONTROL和UNIT1 CONTROL。

最终 `/tmp/pdf-measure-userunit-browser-20261112-green02/summary.json` 的ok=true，Chromium140.0.7339.16。冻结构建 `/tmp/pdf-measure-userunit-static-20261112`，manifest SHA `e8a46b104263594fe6ba6d5f9403e01377bed3b31e676b220e5ece5a35f1dafa`；48份实际JS/CSS的HTTP/磁盘SHA逐项相同、manifest前后不变，page/console/HTTP/asset错误为空。

真实UI操作与预期：

| 顺序 | 页面单位及用户操作 | 标签 |
| --- | --- | --- |
| 1 | UserUnit2，原坐标80单位，标定为2m | 2.00 m |
| 2 | UserUnit1，原坐标80单位，沿用比例 | 1.00 m |
| 3 | UserUnit1，原坐标160单位，沿用比例 | 2.00 m |
| 4 | UserUnit1，原坐标80单位，重新标定为2m | 2.00 m |
| 5 | UserUnit2，原坐标80单位，沿用新比例 | 4.00 m |

过程中实际Undo/Redo保持标签；旧标签不因重新标定重写。五项均actual preview已应用、跳过为空，无页边裁切提示；普通无告警测量按既有规则隐藏确认面板并正常保存，不新增门槛。真实保存修订4→5、界面下载链接核对及浏览器HTTP下载、新编辑URL重开身份全部通过。

独立pypdf读取实际下载AP的各个Tj、L、Helvetica资源、页面单位/页框和原正文，按PDF物理单位重新推导数值2/1/2/2/4。原坐标仍为 `[110,240]→[190,240]` 或 `[270,240]`，没有把坐标预乘UserUnit。第一标定线物理长度160pt。源SHA `509feddb8ec0d0488808385cd70dd1e32e08b0a2953a4a03c72171633529d442` 不变，下载/重开SHA `4a74492fb42af6c3c4da2dd6da1e5e09f444eab7e49d73f93acd0852e56183da` 一致。

首个GREEN目录中五标签和实际预览已正确，但脚本复用了页边告警场景的“确认面板必须可见”断言而timeout，保留该失败证据；改为核实际PDF预览状态、仅实际出现面板时确认，未改产品。测试刻意重复部分线段坐标以验证重新标定不覆盖旧标签，因此截图有叠印；本批以各个独立AP核标签，不以该截图声称像素可读性通过。

root独立复核summary、全部48资源、manifest与下载文件SHA，并目视实际预览图。新Python smoke文件Ruff/编译、新mjs语法和git diff检查通过。本限定场景是真实UI、HTTP、引擎、保存、下载重开链，使用隔离仓储，不冒称生产DB或所有PDF来源均已验收。

## 边界

UserUnit归一化处理的是PDF物理单位，不自动识别图纸的制图比例。会话比例仍以用户给定的已知长度为准；页面制图比例不同仍需重新标定。比例不持久化，保存/重开后仍按原有规则重新标定；已生成标签保留。此改动不修正历史文件可能已有的错误长度，也不扩大原编辑来源权限。
