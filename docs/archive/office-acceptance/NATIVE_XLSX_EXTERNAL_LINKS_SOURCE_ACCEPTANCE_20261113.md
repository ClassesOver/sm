# XLSX ExternalLinksPanel 源族验收（2026-11-13）

固定上游：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。
本族不涉及图表格式、打印、Word、PDF、PPTX。

## 源控件 / callback / 本地实现

| 源控件或行为 | 源 callback / native | 浏览器等价 | 当前证据 |
| --- | --- | --- | --- |
| 非探测列表：源、状态、sheetNames | listExternalLinks / Rust external_links::list | 只读当前包 externalReferences→OPC关系→externalBook，校验命名空间/关系类型/身份，不 fetch Target | reader/writer 12 定向测试 |
| Update | save→updateExternalLinks→apply overlay→save | capture 当前草稿重放bytes；仅选中授权文件bytes；展开受支持引用交既有 Univer executeFormulas；typed缓存原位写入，原公式保留；NativeDraft统一保存 | 实际Univer scalar/range/bool/text + main Update24/Undo6/Redo24/save/reopen |
| Locate(index) | 主进程按session/link index解析，不接受renderer路径，OS showItemInFolder | index绑定当前快照，展示用户已授权文件名/SHA/尺寸；未授权明确说明；不探测OS/URL | panel/host+真实browser r1未授权/授权SHA检查 |
| Change Source(index) | OS文件选择，externalLinkPath Target retarget，不改f/cache | 原生 file input 选择 .xlsx，6 MiB上限，SHA/size/MIME/包结构验证；retarget + bytesBase64绑定操作随现有scope/source SHA NativeDraft固化；不立即更新值 | ZIP无关part保持；cancel/late/readonly/stale专项 |
| Break(index) 两阶段确认 | cached typed literal，删除owned link及rels、workbook reference、content type，survivor [n]重排 | 迁移固定源gateway计划器，接现有assemblePackage/assertOnlyTouchedEntriesChanged/operations；保留Undo/Redo与统一保存 | typed/parts/renumber/quoted string/shared-string/canonical/namespace/保护专项 |
| busy、取消、关闭、empty、未保存说明 | 源panel按钮状态/notice/close | 全部控件；回调前后generation/current/editable核对，异步文件读取晚到不得写入 | panel5/host3 |

## 边界

- 无任意URL获取、无本地路径读取、无业务数据库凭据传递。固定源 desktop Update 的文件路径可达判断被浏览器显式文件授权取代。
- 当前 Update 支持授权来源中的字面单元格和受限矩形范围；真实计算使用已安装Univer，不自造公式计算器。
- 来源中含公式而未受控计算、shared/array/dataTable外链、外部名称/3-D、OFFSET/INDIRECT/ROW/COLUMN等依赖引用形状、外部访问函数、引擎错误/数组结果：不写新缓存，返回具体位置和未更新原因。不能冒充全公式更新成功。
- 未授权或URL来源保留缓存并显示未更新。新修订仅保留包内target/cache，不把授权文件写入XLSX包；须重新授权来源。当前修订本地草稿可恢复授权bytes。
- Break遇defined name、CF/DV/x14、chart、shared等不能安全literal化引用，整次编辑拒绝并说明；这不是报告验收/下载门禁，未改变非阻断发布协议。
- 保护工作表不允许Break或缓存修改。重复/别名所有权、外来namespace、过期target/formula、伪造source SHA拒绝使用对应输入。
- 保留外链原公式的缓存投影与公式计算result适配，避免Univer不支持外部引用时自动改成 #REF!；原公式由facade/保存保持。

## 证据与状态

证据根 /home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113/xlsx。

- writer 12/12（external-links-writer-final.log）。RED分别保留writer/update/binding/guards/canonical/quoted/formula-domain/namespace日志。
- panel5 + host3 + 真实Ribbon入口1（external-links-ribbon-green.log）；真实Univer缓存跨自动重算保留、scalar/range/bool/text。
- native wrapper4（external-links-native-green.log）；仅证明wrapper协议，mock共享桥接，不能证明真实保存链路。
- 真实Python→冻结CLI桥接1（external-links-delivery-red.log / external-links-delivery-green.log）：独立openpyxl/lxml夹具覆盖四操作，原先缺少delivery/xlsx.py白名单而失败，补齐后独立ZIP/openpyxl回读24及未变工作表。
- main真实Univer集成1（external-links-main-sixth.log）：Update→Undo/Redo→统一save→validation false链接仍可见→新identity重开24和原公式。前五次harness问题与失败日志保留，未重跑无关全套。
- 独立zipfile/lxml/openpyxl fixture及browser runner：frontend/smoke/workbook-external-links-smoke.mjs 与 workbook-external-links-verify.py。真实browser-final-v3-r1完成Ribbon、非探测列表、未授权Locate、原生文件选择、授权Locate SHA、实际Update24/FALSE/new text及2条未更新原因、localStorage重载、Break取消/确认与Undo/Redo；保存HTTP422失败。r1未达到下载/新修订重开，不能标整体验收通过。
- r1失败根因：delivery/xlsx.py操作白名单缺少四种external操作，CLI前拒绝。已补齐白名单；静态v3与冻结CLI无需重建，Python修复由root独立冻结。r1真实POST body因runner先断言再落盘而未保留，server也仅记HTTP元信息；预检fixture-check/request.json不能冒充真实r1请求。
- r1保留failure.json、failure.png、edited.png、http-evidence.json、server.log与输入身份；pageerror及外部请求均为空。两条懒加载asset请求在重载期间ECONNRESET，需保留并单独核对，不能隐去后宣称全部资源成功。
- 修复后专项reconstructed-draft-continuation-v4-r1：复制r1输入并按同scope/document/revision/source SHA重建等价四操作草稿；不是恢复r1丢失的真实payload，也没有重复完整控件流程。显式加载冻结v3 office_engine/native_office及v4 xlsx.py，真实POST body在状态断言前落盘。save HTTP200登记revision5，下载6033字节，SHA c5f1869c45cdecb65d6a10b5c522e071ecb65579ad34c4b3584e1cd0e5fc2def，新修订重开同身份成功。
- continuation独立ZIP/lxml/openpyxl确认changed parts仅Content_Types、workbook关系、workbook、sheet1四项；removed仅externalLink1及其rels两项；值为24/FALSE/new text/90/11，survivor公式为[1]Data!A1，未关工作表保持原始bytes。validation.ok=false且明确native_source_review_pending，产物仍签发可下载链接，不冒充业务核验通过。
- continuation保留4条asset ECONNRESET及4条console ERR_FAILED（de/ja/ko/fr Word locale懒加载）；同4路径另有实际HTTP200响应且浏览器bytes SHA与v3静态磁盘一致，286个实际asset路径核对成功。pageerror及外部请求均为空，但不能宣称所有资源请求零失败；失败原文仍在evidence.json。未为此重复浏览器整轮。
- root统一tsc发现RibbonCommand及未命令化入口缺口；已补union和actions map，并真实ribbon RED→GREEN1，不以main模拟callback冒充真实入口。
- 未执行全量tsc、共享static/dist构建或预算修改；root统一冻结负责。

统一v2构建tsc/Vite通过但workbook-main预算256.6>253KiB；按root授权仅新增vite manualChunks外链UI/host分块规则，原预算不改。最终以root v3构建和真实browser证据为准。
