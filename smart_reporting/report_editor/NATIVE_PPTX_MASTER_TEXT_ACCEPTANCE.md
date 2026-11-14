# PPTX 母版和版式文字专项验收（2026-11-13）

本专项复用 NativeDraft、现有预览/渲染树、保存、修订及核验文件身份后的非阻断下载链。当前产品已冻结，定向测试、`352eb5` 完整保存层的真实 HTTP 保存/下载/新修订重开及独立部件回读通过；后续统一 `b8b97e` 最终入口的零保存续验也通过。以下结论仅覆盖已有顶层文字的纯文字改写，不扩大为完整母版功能。

## 固定源与接入边界

固定源 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

- 源 `Ribbon.tsx` 的 `onSlideMaster` 经 App `masterEnter` 进入 `MasterView`，选择实际母版/版式部件后以 `masterEditText` 提交文字；preload/main 接到 part-addressed `runTxn/setText`，写入触及部件并重新解析页面继承。
- 本地入口为「视图 → 母版和版式文字」。展示实际源 `SlideThumb`，选择当前源文件列出的母版/版式部件与已有顶层文字对象，用纯文字 textarea 进入同一 NativeDraft；未另建工作区、保存协议、历史或下载系统。
- 源事务直接使用本地固定 vendor 的 `runTxn`，目标别名为 `e_<SPID>`。不复制源 setter，不接收客户端 XML 或任意 part 路径。协议仅允许源列出的规范 master/layout 部件、唯一数字 SPID 和具备文字 body 的顶层 shape/text。
- 纯文字整段改写遵循源 `setText` 语义，会合并混合 run 并沿用源判定的正文主样式，不宣称每个原 run 的独立格式均保留；超链接及动态字段按源 helper 处理，不笼统拒绝。动态字段缓存可能在 PowerPoint 中重新计算。
- 当前不是完整富文本 `MasterView`：逐 run 编辑、组内子对象、创建/删除母版或版式及其他结构操作仍是明确缺口。文字对话框与源缩略图不代表完整母版视觉编辑器。

## 定向验证

证据目录 `/dev/shm/office-next-pptx-master-text-20261113`；本专项没有重跑完整测试、统一 Vite 或全局类型检查。

| 范围 | 验证与结果 | 证据 |
| --- | --- | --- |
| Python 协议 | 17 项通过；检查合法转发、输入不变、换行规范、规范路径/SPID、非法字符/额外载荷、重复与数量/长度预算 | `green-protocol.log` |
| 实际 edit bridge / 固定源事务 | 3 项通过；真实部件 inspect、源 `runTxn/setText` 等价、未触及实体部件逐字节保持、伪造身份拒绝、混合 run/链接/字段语义及无 dist 的 tsx 回退 | `green-bridge-03.log` |
| UI 与相邻入口 | 3 文件 47 项通过；母版入口、同一草稿、预览、Undo/Redo、同值无修改、IME、旧对话框保护及既有大纲/阅读/Ribbon 回归 | `ui-regression.log` |
| 未打包 tsx 原生 raw 依赖 | 六个固定 vendor 文档 URL 白名单窄化后，仅重跑对应混合 run/tsx 用例，1 项通过 | `green-tsx-static-allowlist.log` |
| HTTP 夹具准备 | 两页共享真实 master/layout，各加入一个已有顶层文字；冻结 render 桥回读确认两页确实继承两处文字 | `prepared-fixture.pptx`、`prepared-render-tree.json` |

`pptx-master-text.ts` 针对未打包 tsx 的 loader 只匹配 `text/element/insert/table/slide/deck.md?raw` 六个静态 vendor URL，并在导入完成后 deregister；请求文字、部件身份与模型数据均不参与 URL。打包 bridge 使用 esbuild `--loader:.md=text`，不安装此 hook。

## 浏览器验收运行边界

验收脚本为 `frontend/smoke/pptx-master-text-server.py`、`pptx-master-text-smoke.mjs` 和 `pptx-master-text-verify.py`。HTTP 夹具复用真实 capability、组织/用户/任务绑定、工作区授权、导入、CSRF、保存、发布及下载接口；repository 为既有内存夹具，不作为生产数据库授权验收。

静态资源和 PPTX 引擎使用 root 的物理冻结快照；Python 在现有 live 仓库运行，开始/结束逐个比对 `BACKEND-SNAPSHOT-SHA256.json` 的 102 个文件，并明确记录 `notClaimingPythonIsolation=true`。不得把该模式记为隔离 Python 仓库运行。

没有修改三份总审计文档，也未 commit/push/deploy。

## 352eb5 冻结资源与完整保存层

物理前端/引擎快照：`/dev/shm/office-next-split-master-chart-home-20261113/source`。root 独立完成最终 Vite、类型检查、四桥、原体积预算与预算合同，exit 均为 0；本专项没有重复这些全局检查。`SOURCE-SNAPSHOT-SHA256.json` 的清单身份为 `d5a061eae017db99337a09a583cfba52e91eae34e2d3d60e3218a3f9f8c381bf`，本轮 HTTP 起止未改变。

`browser-02/summary.json`、`browser-02.log` 记录完整验收；`backend-before.json` 与 `backend-after.json` 的 102 个 live 后端文件均匹配冻结基线，漂移为空。最初 `browser-01` 是验收脚本误请求不存在的 GET `/api/deck`，保存前失败、保存次数 0；失败截图、日志和 HTTP 证据完整保留。脚本随后使用现有 POST `/api/preview` 读取 `model`，没有为此修改产品。

- 实际选择母版和版式部件、源缩略图、同值采纳/取消无草稿变动、IME 拒绝采纳均通过。
- 两处文字加入同一 `editSlides.masterTextEdits` 草稿，Undo/Redo、刷新恢复、390px 对话框宽度通过；实际渲染树按源 lines/runs 重组后，确认两页都继承新的母版全文和两段版式文字。
- 仅执行一次现有保存，注册修订 2；签名下载身份与回执一致，新修订重新打开后两处真实文字均为更新值。
- page error、console error、HTTP error 均为空。`master-source.png`、`layout-edit.png`、`layout-mobile.png`、`layout-reopened.png` 已逐一目视检查；`inherited-normal.png` 拍摄时 canvas 仍显示异步更新状态，因此它不单独作为稳定普通画布的最终视觉证据。

| 冻结身份 | SHA256 / 实际入口 |
| --- | --- |
| manifest | `352eb5fc3903b0d6c145c1f1e873e2ad983a2f58b7ec1e0d3567f18b3ba1a560` |
| 实际 HTTP native HTML | `a0057f54cf306d8929d2b90ca3378879dd4c59f181cec839ba391b0fbd2c123b` |
| 实际入口脚本 | `assets/lazy-preload-helper-BPPmGX_j.js`、`assets/lazy-unified-main-CSgD_zNW.js`，均确认实际加载 |
| edit-pptx.mjs | `e341f41736545fcb30191633fb1ceb3bf98c221477ea088e51803ee29f949785` |
| render-pptx.mjs | `ee143300bcfa63fd201aede1a5577368c9d4649f820071e0c6fdd6312ec67005` |

153 个不同 URL 的实际静态资源（138 JS、15 CSS）全部逐个计算 SHA256，匹配物理冻结文件；`http-evidence.json` 的 459 次实际静态响应（含刷新及修订重开）也逐次校验，未用 manifest 列表冒充网络加载证据。

`readonly-03/summary.json` 对同一下载文件（下文 SHA256）进行零保存续验，专门等待普通画布完成初始化及字体绘制后拍摄第一页、第二页。`inherited-settled-page1.png`、`inherited-settled-page2.png` 已逐一目视检查：两页均显示新母版文字与新两段版式文字，正文和各自讲稿保留，状态为正常选择提示。也重新打开两处文字对象核对真实值。该层保存请求 0、完成修订 0、operations 为空，153 个实际静态资源身份匹配，page/console/HTTP error 为空，102 个后端文件起止仍无漂移；未重复业务保存或签发。

`final-product-identity.json` 逐个确认本专项 11 个产品文件与物理 frontend/engine 或后端基线一致。验收结束时外部放映/动画会话继续更新了 live `slides-main.ts` 的 `openSlideShow`，本专项保留该外部修改，没有将其混入冻结验收：物理快照 main SHA256 为 `8d56d8389abca6b164a4418ecffdc8de1f2d3bf9fb5a21b3df02b61dfadc0eaa`，live main 为 `005447725beead9b281362ce7ee91bd518772b429b32097161836a9f1b8b9d7d`。不得从本专项结果推断该后续播放链已经验收。

## 独立产物回读与非阻断验收状态

下载 PPTX SHA256 为 `a50b97dd264d55f4f94659d2318a149c29535c2cb5c89029489a49a2065d5ac9`。`browser-02/independent-verify.json` 和 `independent-verify.log` 由独立 ZIP、lxml 与 python-pptx 回读：

- 仅 `ppt/slideMasters/slideMaster1.xml`、`ppt/slideLayouts/slideLayout7.xml` 两个实体部件改变。
- SPID 9001 为 `母版品牌更新 <&> 😀`；SPID 9002 为 `版式品牌更新` 和 `第二行` 两段文字，XML 字符转义、emoji 与换行回读正确。
- 其余 45 个实体部件全部逐字节保持，含所有页面、讲稿、关系与媒体；独立 python-pptx 仍能打开两页，并验证每页原有正文与讲稿。
- 回执明确 `validation.ok=false`，原因 `native_source_review_pending`，信息为“文件已保存；原生编辑内容尚未重新核验业务事实与完整版式。”；已核验身份的 PPTX 照常签发并下载，没有将该状态改为验收通过。

## b8b97e 最终统一入口零保存续验

其他格式的初始化修复使统一入口重新构建；PPTX 产品和两桥未改。root 保留 `352eb5` 静态资源及 `d5a061` 源码清单历史，完整保存层仍有效。最终入口以同一物理根目录的新 manifest 为准，不重新执行本专项保存或签发。

`readonly-04/summary.json`、`readonly-04.log` 记录：重导入同一个 `a50b97dd…d5ac9` 下载 PPTX，等待正常普通画布与字体绘制，选择两页并分别截图；两张 `inherited-settled-page1.png`、`inherited-settled-page2.png` 均已目视确认母版全文和两段版式文字，原正文/讲稿保留。重新打开两处文字对象仍得到保存值。operations 为空、保存请求 0、完成修订 0，未重复完整保存。

| 最终身份 | SHA256 / 入口 |
| --- | --- |
| manifest | `b8b97ee76d41a565f94e9f8c902e226031ada09ad9cd3bcf52deb886f421f04c` |
| 实际 native HTML | `aaa3eb21c2eb976afff3d1ae6a7ace757b75e2613a1b7272c6613cc4728a29c2` |
| 实际入口脚本 | `assets/lazy-preload-helper-BPPmGX_j.js`、`assets/lazy-unified-main-D3q1w4ic.js`，逐个确认实际加载 |
| 源码身份清单起止 | `44adefabe1fc5c1fcdf412aabfcb2d7abb86449c06cbbcf6f9ce9ed10da818b3` |

153 个实际静态 URL（138 JS、15 CSS）全部匹配新冻结文件的 SHA256；page error、console error、HTTP error 为空，102 个 live 后端文件起止与基线一致。edit/render 两桥身份仍分别为 `e341f417…49785`、`ee143300…67005`。本专项不从零保存续验推断其他格式修复或最终全局类型检查结果，这些由 root 独立记录；live 外部播放链继续排除。
