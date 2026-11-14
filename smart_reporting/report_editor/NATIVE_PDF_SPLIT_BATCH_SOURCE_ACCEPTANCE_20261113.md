# PDF 每 N 页拆分多文件固定源接线与验收

证据根为 `/dev/shm/office-next-pdf-split-batch-20261113`。本专项接续既有固定源缺口
核对，仅处理每 N 页生成独立 PDF；不把 `splitPages` 每页切格或 N-up 合并页面当作
拆分文件功能。产品范围不含并发的 heading 目录导航修改，也不覆盖其它专项证据。

## 固定源与恢复时实际缺口

固定源 `/home/junge/pros/genoffice-source-full` 的 HEAD 已实际核实为
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- `apps/pdf/src/renderer/App.tsx`：`confirmSplit` 要求每份页数为整数，且
  `1 <= N < pageCount`，至少生成两份。`splitPdfToFolder` 走 `runFileOp` /
  `flushThen`，先保存脏草稿，后续索引属于保存后的可见页序。
- `apps/pdf/src/shared/ipc.ts`：`SplitPdfRequest` 包含 `path/chunkSize/baseName`，
  成功返回输出目录与份数，取消可返回 canceled。
- `apps/pdf/src/main/pdf-main.ts`：验证当前视图的来源授权，选择目录，调用
  `splitPdfBytes` 并按 `<safeBase>-1.pdf` 等逐份写出，不自动打开多份标签页。
- `apps/pdf/src/main/save-pdf.ts::splitPdfBytes`：按连续页序分组，尾部不足 N 页
  也成为独立文件。每份复制页面，不保证保留来源级书签、附件或交互结构。

恢复时已检查 live：`pdf-page-ribbon.ts` 的 `page.splitPdf` 仍禁用；服务端没有
split-pdf 路由。只有既有 `splitPages` 切格，不存在可复用的每 N 页多文件实现。
源码身份及上述四个上游文件 SHA 记录于 `source-identities.json`，其 current 身份
只针对记录时刻，最终构建另行绑定物理快照。

## 最小接线与非阻断边界

前端新增 `pdf-split-dialog.ts`，启用既有 Page / Combine & Split 的拆分 PDF。
输入页数按固定源范围验证，取消不保存也不拆分。返回所有份的页范围、文件名、
具体告警、下载及可用的独立编辑入口；服务端返回的链接只接受同源 HTTP(S)。
结果可关闭后重开，未完成请求不重复提交；关闭不撤销服务器已生成产物。

`NativeSession` 新增独立 `flushForFileOperation`，不改变既有 `save()` 参数或返回
契约。其先调用原视图 flush，再走原保存流程的快照、实际预览确认及保存接口。
未确认或保存失败时不提交拆分；修订未登记时保留原下载和草稿，提示完成登记后
继续。已登记回执可复用，不为重试多保存一次。

PDF 局部回调沿原签发的 editor grant 授权新修订，读取新修订 context/CSRF，核对
文档、修订、PDF SHA 和 scope 后，从该新修订拆分。来源及页序来自真正保存结果，
不把原始页序或旧授权假作已保存来源。需要预览确认时沿原界面核对并勾选后再次
拆分，不自动确认，也不静默跳过未执行项。

服务端 `native_pdf_extract.py::split_pdf` 先验证真实来源总页数，顺序分组；每一份
调用原 `extract_pages`，继续复用 `delivery/pdf_native.py::extract_pdf_pages` 的
固定源 writer、授权工作区、独立来源身份、派生登记和非阻断发布。没有新增另一套
writer、工作区或签发实现，PDF bridge 无须为本功能新增构建接口。

单份生成失败、实际文件缺失或身份不匹配仅拒绝对应份；记录原因后继续后续分组。
登记、写入回执、引擎回执或后置复核失败时，只要实际文件可读且身份匹配，原链路
仍签发该份下载。批量和逐份 validation 均保留未验收或失败状态，不标记业务通过。

兼容范围沿既有提取器：含 AcroForm、批注或保护信息的来源暂不支持，界面已明示；
来源级书签与附件不保留。每份页数沿原提取契约上限10000，来源总页数也受本地
10000页边界约束。这不等于任意复杂 PDF 的无损拆分支持。

## 本轮定向 RED / GREEN

没有运行完整 suite，没有独立执行统一前端构建或改写共享 static/dist。

| 证据 | 实际结果与覆盖 |
| --- | --- |
| backend-red.log / .exit-code | 原 split-pdf 路由404，功能测试失败，退出1 |
| session-red.log / .exit-code | 两个文件操作测试因缺少flush接口失败，退出1 |
| dialog-red.log / .exit-code | 新对话框模块尚不存在，测试收集失败；不计作行为RED |
| backend-green.log / .exit-code | 8 passed，真实ASGI/原引擎/下载/pypdf；覆盖连续分组、尾页、同请求重试与来源不变；CSRF、Origin、SHA、修订、布尔/零/N等于总页数拒绝 |
| nonblocking-green.log / .exit-code | 8 passed：7种批量故障注入和签发静态守卫 |
| frontend-green.log / .exit-code | session10项和dialog9项通过；当时旧ribbon能力预期漏新启用split，1项失败，未掩盖 |
| ribbon-green.log / .exit-code | 更新启用能力预期后仅重跑该文件，1 passed |

7种批量故障注入登记于 `test_http_publication_lineage.py` 的
`test_pdf_split_http_preserves_other_parts_and_verified_downloads_on_faults`：第二份
生成失败、登记失败、伪造引擎回执、写后回执异常、独立复核异常、实际身份被替换、
实际文件缺失。真实HTTP下载经 pypdf独立检查；第二份不可用时第一/三份仍成功，
来源字节不变。`split_pdf` 已加入 `_SIGNING_CHAIN`，静态守卫实际通过。

前端19项覆盖保存预览确认复用、未登记保留下载且停止派生、新来源SHA提交、逐份
下载与具体错误展示、输入边界、确认失败不拆分、等待期间关闭后结果保留。上述
Python测试只有既有 imghdr 弃用告警，没有因业务告警将validation改为通过。

统一构建第一阶段类型检查、四桥及Vite通过，但PDF主chunk为255.7 KiB，超过既有
250 KiB预算；该阶段manifest只留失败记录，不作最终验收。没有抬高预算。随后只将
本次拆分职责提取为 `pdf-split.ts`，原PDF宿主仅在用户首次点击拆分时
`import('./pdf-split')`，对话框随该模块加载；销毁后不挂载迟到模块。不是仅作静态
chunk拆分，也没有将无关旧PDF功能挪入任意块。`lazy-boundary-tests.log` 记录来源
授权3项与对话框9项共12 passed，新增验证同SHA新修订仍使用新授权、scope不符时
不提交拆分。预算与最终构建结果等待root统一复核，不由本agent重复全量构建。

第二次统一类型检查和Vite通过，主chunk降至250.7 KiB，仍超过原250 KiB预算。
继续只将拆分同步入口提取为 `pdf-split-host.ts`，通过单条专名chunk规则独立承载。
该小host随PDF首次载入，**只有 controls/dialog 在首次点击时真正延迟加载**；不将
静态小host宣称延迟。宿主3项定向测试实际通过，验证并发打开复用、销毁后不挂载
迟到模块及忙/刷新/无flush脏草稿禁用边界。

第二次修复前重读发现live有外部并发PDF compare改动，本专项未删除或覆盖它们，
也未将其采入本批冻结。`frozen-overlay/pdf-main.ts` 是从root物理快照原main派生、
仅应用split-host局部替换的精确候选；同目录保留patch、host、vite配置及身份JSON。
候选main SHA为 `1b0f6b9469ac770f41c85369e4347df7c688facf3bc5594ce11ef3b3038ffe16`，
与保留compare的live main有意不同。最终验收只绑定统一物理快照，不称所有live能力
均已验收。真实剩余缺口清单中的compare状态也只代表其记录时点，不否认后续并发
实现存在；该并发功能不在本专项验证范围。

## 统一冻结浏览器验收入口

`frontend/smoke/pdf-split-batch-smoke.mjs` 和 `pdf-split-batch-server.py` 已准备，
语法/py_compile/定向diff检查通过。runner强制显式传入
`PDF_SPLIT_BATCH_STATIC`、`PDF_SPLIT_BATCH_ENGINE`、`PDF_SPLIT_BATCH_MANIFEST`，
默认独立端口4440；不自动使用 live dist。宿主复用现有真实路由与内存身份/仓储
夹具，输入为五页真实 PDF。

拟验收路径为：取消不保存→修改文档属性并反序→未确认时停止→核对真实预览→
勾选确认→一次保存到新修订→新授权上下文按 N=2 拆成三份→实际下载与子文档重开→
独立pypdf验证 `[5,4] / [3,2] / [1]`，同时核对原文件SHA未变。实际完成后追加
冻结manifest、响应身份与截图结果；本节准备状态不构成最终冻结浏览器通过。

## 真实剩余缺口

`next-gap-inventory.md` 保留本时点只读清单：多输入合并 PDF、双来源文档比较、
静态表单完整填写流程、签名字段、自动字段检测及完整设计预览等仍有未接线入口。
证书签名及签名面板还需区分固定源支持情况与服务端密钥边界。没有因本次拆分成功
宣称这些能力已补齐，也未实施它们。

## 最终冻结首次 HTTP 与初始化回归（2026-11-13）

root 统一四桥、类型检查、Vite 和原预算通过，PDF 主块为249.3 KiB。
首次最终manifest为 `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560`。
`browser-frozen-final` 入口失败，退出1，实际 **0次保存、0次拆分、0个派生下载**；
截图显示初始化异常 `Cannot access 'P' before initialization`。原生入口catch将异常
写入状态栏，故pageerror/console为空不代表初始化成功。原失败目录完整保留。

真实根因为首次 `updateControls()` 早于来源 `api.file()` 和 `const model` 初始化，
拆分宿主的状态回调却无条件计算 `state().length` 与 `hasUnstagedText()`。
新回归 `pdf-split-initialization.test.ts` 直接调用真实 `createPdfEditorView`，验证
在来源未读取时应抵达文件读取边界且拆分入口禁用；冻结旧代码实际抛出
`Cannot access 'model' before initialization`，`initialization-red.log` 退出1。
前置路径、worker收集与Python命令错误另留preflight日志，不计行为RED。

恢复两处 `document` 前置短路后，同一回归与宿主3项共4 passed，
`initialization-green.log` 退出0。live两处表达式在本agent恢复前已有外部并发修正；
本agent未重写live产品，只给冻结main精确应用这两处表达式，并新增回归测试。
`frozen-overlay/initialization-fix/` 保留修改前后文件、patch与身份登记：
main由 `1b0f6b9469ac770f41c85369e4347df7c688facf3bc5594ce11ef3b3038ffe16`
变为 `ddb7f90253118e679091f80c1118fc4d0a2383b5c9f81748c9081686718edd6f`。
没有复制并发compare/native-AI，也没有调整预算；等待root重建后的新manifest才能
重新执行完整PDF拆分HTTP链，当前不能宣称该链已通过。

首次Python身份前置脚本误用了source路径，后纠正为实际backend-baseline；记录写于
入口开始之后但无任何mutation，不冒称真正启动前。前后8个Python文件均与物理快照、
登记SHA一致，详见该失败目录 `python-identities-before.json` 和
`python-identities-after.json`；下次必须先成功核验再启动。

## 修复后最终冻结 HTTP 结果

root 重新Vite、原预算与预算契约均退出0；最终manifest为
`b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c`。
`browser-frozen-initialization-fixed.log` / `.exit-code` 为退出0，独立目录
`browser-frozen-initialization-fixed/evidence.json` 为 `ok:true`。旧352eb5入口失败目录
未覆盖。该轮没有再改产品或重复完整suite。

实际链完成：取消不保存；文档标题改为 `Split saved title` 并反序；未勾实际预览确认
时0次保存/0次拆分；手动核对并勾选后唯一一次save，将parent-document修订4保存为5；
授权新修订并读取新context/CSRF，从修订5发送唯一一次split-pdf。N=2得到三份，逐份
执行真实浏览器download，文件SHA/大小与回执一致。独立pypdf回读页序为
`[5,4] / [3,2] / [1]`，保存源标题正确且完整反序，原来源SHA未变。第一份派生文档
实际重开为2页。保存与三份结果的validation仍为false，不伪称业务复核通过。

实际HTML字节与冻结native.html一致；60个JS/CSS响应均与物理文件SHA及manifest映射
一致。同步split-host随入口加载，controls/dialog在首次拆分打开前没有加载、打开后
实际发生动态请求。pageerror、console error和HTTP error均为空。

01:45:33 UTC真正启动前与01:46:18 UTC结束后的8个Python链路文件均逐一读取live、
backend-baseline与BACKEND登记SHA，全部相等且前后稳定；不宣称Python物理隔离。
桌面、390px窄屏首部和尾部三张截图均实际目视：文字、告警及逐份下载/打开按钮可读，
窄屏可滚动至第三份，固定底部按钮可达，宽356/scrollWidth356，无横向溢出。
具体回读、视觉及身份记录分别在同目录 `independent-verification.json`、
`visual-review.json` 和 `python-identities-{before,after}.json`。

结论仅覆盖本次固定源“每N页多文件拆分”链；并发live compare/native-AI不在该物理
冻结与专项验收范围，前述其他真实缺口仍另行处理。
