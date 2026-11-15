# PPTX 经典批注独立验收

日期：2026-11-11。仅经典根批注查看、新增、逐条删除。回复、解决、账号作者身份、多人协作不在范围内。生产实现由其他专项负责；本文件保留真实来源、失败和最终构建验证的独立证据，不把 fixture API 当作真实部署鉴权链。

状态更新：2026-11-11 15:45（Asia/Shanghai），下文“最终冻结浏览器与 HTTP 验收”已补齐 GREEN。早期准备和 RED 段落保留为历史记录，不再表示当前验收状态。

## 真实文件与独立回读

仓库 helper：smart_reporting/reporting/tests/pptx_comments_fixture.py，生产不引用。create(variant) 使用 python-pptx 生成两张真实正文页，再在实际 ZIP 中写标准经典 comments、commentAuthors、各页关系和 Content Types。readback 用独立 ZIP/lxml 按页关系解析 (authorId,idx,text)，不依赖 inspect 返回数组；verify 对保存下载文件逐部件核验。

- 页0：Alice 爱丽丝 (authorId=0,idx=1) 和 Bob 鲍勃 (authorId=1,idx=1)，相同 idx 不同作者；页1：Alice (0,2)，独立最后一条评论。批注含中文、emoji、XML 特殊字符与引号；正文也含中文/emoji/特殊字符。
- custom/preserved.xml 含未知内容及 presentation 未知关系，要求字节原样保全。新增宿主作者由真实 Python 内部注入固定“用户”，不把它称为登录账号或协作身份。
- modern 变体包含真实 2018 comments 关系、现代 part 与 Content Type；broken 变体包含失效 authorId 引用。必须明确只读原因，不能把未知/损坏来源误报成可写空批注。
- 初始真实来源：/tmp/pptx-comments-fixture-20261111/{classic,modern,broken}.pptx；每种对应 *-zip-readback.json 独立回读结果。构建浏览器运行时重新生成并将真实文件/身份写到其各自证据目录，不复用 mock 数组。

## 初始严格 RED

/tmp/pptx-comments-source-red-20261111.log：当前生产引擎 inspect 两页实际 PPTX，返回 comments=[null,null]；断言“real PPTX inspect lacks classic comments projection”失败。该失败证明宿主未投影经典批注，不是 source 文件空缺；独立 ZIP/lxml 已核对源中三条评论。

## 构建后专项准备

frontend/smoke/pptx-comments-classic-smoke.mjs，node --check exit0；仓库 helper py_compile exit0。必须由 root 统一引擎 bundle / 前端 build 后给精确 PPTX_EXPECTED_MANIFEST_SHA256 才运行，本 agent 不自行构建。

classic 模式准备断言：中文审阅/新建批注/批注窗格与真实 SVG；查看两页、折叠重开不改草稿；页面重排后仍按原 source 定位，再 Undo；取消未发布不入草稿；新增后本地撤回；精确删 Alice(0,1) 而 Bob(1,1) 保留，Undo/Redo；删页1最后(0,2)；新增一条、Undo/Redo、reload恢复；第二条中文新增未失焦保存；实际下载和修订2重开。独立 ZIP/lxml 确认未删错同idx不同作者，页1最后评论 part/关系/override 清理，两个正文 XML 与全部未涉及 part 字节不变，python-pptx 正文回读不变。

boundaries 模式独立查看 modern/broken 两个真实来源，核对具体只读原因、新增/删除禁用、草稿未改变、零save。每种有截图与实际 source SHA。两模式均逐个核对实际 JS response 原始字节 SHA 与磁盘、manifest/bridge/helper 身份、浏览器错误和窗格布局几何；API routes 明确为fixture，inspect/preview/save/render调用真实生产Python/Node。保存回执故意 validation=false 时界面保留具体原因与真实PPTX下载，不能标记版式验收通过。

当前仅完成准备和初始 RED；没有执行尚未构建的浏览器GREEN，未重复旧完整suite/旧浏览器，最终结果待统一构建后追加。

## 最终冻结浏览器与 HTTP 验收

2026-11-11，本轮只收口经典批注专项，没有修改产品批注代码。修正三个验收问题：浏览器脚本允许指定独立静态目录；桥包身份跟随生产 `AGENT_REPORTING_SLIDES_ENGINE_DIR` 配置（HTTP 测试也使用同一 `engine_dir`）；文件夹具在 inspect 结果中补入由实际 PPTX 字节计算的 SHA256，避免下载身份断言比较到 undefined。未放宽身份、XML、保存或只读断言。

### 构建身份与失败记录

- 证据根目录：`/tmp/pptx-comments-acceptance-20261111/`。复用本轮开始时已有的构建产物，完整复制到独立 `static/`，没有重新生成前端构建，也没有覆盖共享 static。627 个静态文件在验收前后逐项 SHA/大小一致。
- 冻结 manifest SHA256：`a03fdb4dfefb19bc75090dc448e2dfc1f830e13ba6a7a5ef48fab91e646f1967`。
- 当前源桥独立打包到 `runtime/dist/`：`edit-pptx.mjs` SHA256 `e910df47b49388709e27c968424bf1b37a4095cb11455e19c80809e7ab6a08a9`；`render-pptx.mjs` SHA256 `05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`。
- 首轮沙箱内 Node→Python 子进程出现 EPERM/超时，保留 `classic.log` 和 `import-diagnostic.log`；获准后在沙箱外运行本地浏览器与 HTTP 专项。`classic-unrestricted.log` 和 `boundaries.log` 保留夹具缺少 SHA 的失败，`http-red.log` 保留硬编码引擎路径导致导入返回422的失败；未把这些记录计为通过。

### 已通过的定向验证

- 后端真实文件和协议：`test_pptx_comments_native.py`、`test_pptx_comments_protocol.py` 共32项通过，见 `backend-final.log`。
- 前端：`slides-comments.test.ts`、`slides-comments-ui.test.ts` 共19项通过，见 `frontend.log`。
- HTTP：`test_classic_comments_http_exact_delete_add_and_nonblocking_download` 1项通过，见 `http-final.log`。实际 FastAPI 授权中间件、能力凭证、HttpOnly cookie、CSRF、原生导入/预览/保存/下载与 Node 桥；仓储为内存夹具。验证无CSRF请求403、客户端冒认作者422、保存幂等、原件不覆盖和修订2重开。注入 validator 异常后仍返回 `validation.ok=false`、具体问题与身份正确的下载链接。证据 `http-final/test_classic_comments_http_exa0/evidence.json`。
- Python 编译、测试辅助文件 `F401/F821/F822/F823` 检查、浏览器脚本 `node --check` 通过。HTTP 文件原有 import排序和分号风格诊断未批量修整；第三方 imghdr 弃用警告与 Agno tracing 退出时 logging error 保留在日志，HTTP 进程退出码为0。

### 两条真实浏览器链

`classic-final/evidence.json` 与 `boundaries-final/evidence.json` 均 `ok=true`、进程退出码0。两条链各核对117份实际网络 JS 与冻结磁盘 SHA；page、console、HTTP、route 错误均为空。浏览器 API 路由为显式 fixture，文件 inspect/patch/render 使用真实 Python/Node，不冒称浏览器覆盖生产数据库或部署鉴权。

- 经典链：来源两页切换与折叠、重排按原页身份定位、取消/撤回、精确删除 Alice(0,1) 且保留 Bob(1,1)、Undo/Redo、删除第二页最后批注、刷新恢复、中文/emoji/XML特殊字符、输入仍聚焦时保存，实际下载并打开修订2。保存请求恰好1次。回执故意 `validation.ok=false`，界面显示“已保存，存在告警”和具体原因，下载仍可用。
- 边界链：现代来源与失效作者引用来源显示各自具体只读原因，经典可识别内容仍可查看；新增/删除不可用，不改草稿，保存请求0次。未把现代来源误报为空列表。
- 独立 ZIP/lxml/python-pptx 再次回读下载文件：两页正文和所有无关部件字节不变，另一作者同idx批注保留；最后一条删除后 comments part、关系、Content Type override 清理。仅允许的五个批注相关部件变化。独立复核摘要见 `independent-verification.json`。
- 下载文件 `classic-final/downloaded.pptx` 为43126字节，SHA256 `d1b8ffdf3abb8d863ad913d5d7745e84a31e58751515aa72967ee5b7706fe946`。来源 SHA256 `ceead5003a2f9d2781a80e33523bad01196c73e65cc5432cbfefb386121b85fc`，验收后保持不变。
- 已目视 `comments-delivery.png`、`comments-revision-2.png`、`modern-readonly.png`：批注窗格及中文内容可见，告警下载状态正确，第二页重开为空批注状态；窗格几何断言通过。

本轮关闭“经典根批注查看/新增/逐条删除的专项验收未收口”缺口。回复、解决、现代线程批注、登录作者身份与协作不在交付范围；不代表 PPTX 全面 GenOffice 对齐、当前全工作区构建/类型/预算通过或生产部署完成。未运行完整测试，未提交、推送或部署。
