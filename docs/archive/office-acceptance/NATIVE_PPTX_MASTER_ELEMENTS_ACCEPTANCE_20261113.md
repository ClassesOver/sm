# PPTX 母版/版式文字对象结构编辑专项验收（2026-11-13）

## 范围与源能力边界

固定源为 `/home/junge/pros/genoffice-source-full`，HEAD `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本轮补齐源 `MasterView` 已有部件内的顶层文字框新增、待新增框的文字与位置尺寸修改、原有顶层文字对象删除及待新增框移除。已有普通母版/版式文字改写与本轮结构操作共用 NativeDraft、撤销/重做、预览、保存、修订及下载链。

源证据：`apps/slides/src/renderer/MasterView.tsx:83–97,311–365` 只枚举、选择现有部件并操作其对象；`apps/slides/src/shared/ipc.ts:1891–1904` 声明部件对象操作；`apps/slides/src/main/slides-main.ts:3010–3063` 把增删交给带 `part` 身份的源事务。没有发现源母版/版式部件创建或删除操作，因此没有扩展该能力。源 MasterView 不传 `onEnterGroup`，顶层查找不构成组内对象编辑支持。

本轮没有实现完整 MasterView 等价：现有对象的任意几何变换、填充/描边、逐 run 富文本及组内文字编辑仍有差距。新增文字框使用源 `addElement` 的默认文字样式与 `wrap:none / autoFit:resize`（源点击插入语义），本地坐标输入为 96dpi 像素；宽高是初始文字框大小，源自动适配可能随后改变文字排版。没有复造母版部件、增加手写 XML 输入或把客户端临时身份当作真实 SPID。

## 实现与验证

新增 `pptx_master_elements.py`、bridge `pptx-master-elements.ts`、前端 `slides-master-elements-model.ts` 与 `slides-master-elements.ts`。`native_office.py` 仅做 PPTX 协议键、校验器调用与导入三处集成；`slides.py` 仅转发新字段。源事务加载器从已有母版文字 bridge 提取复用，保留六个静态依赖白名单和 finally 注销。`slides-main.ts` 的增量仅接入该草稿字段、恢复、预览、历史、操作摘要和母版对话框；并行放映功能保留。

局部验证证据位于 `/dev/shm/office-next-pptx-master-structure-20261113`：

- 协议初始 20 用例通过；新增超大整数边界先产生 OverflowError 红灯，改为先检查数值上下界后，14 个非法尺寸/身份用例通过。新增 Python 到既有 bridge 的传输用例及旧母版文字协议合计 18 用例通过。
- 新前端 6 用例与旧母版文字 2 用例合计 8 通过，覆盖新增/修改/移除 pending、删除原对象清理同对象文字草稿、其他部件保留、Undo/Redo、取消、非法尺寸、内外层 IME、过期草稿、恢复、同值编辑无新增历史及只读部件。
- 实际 bridge/source 引擎新增/删除与固定源事务等价、恶意身份不产出文件 2 用例通过；另一个真实 bridge 用例验证普通页面改字与母版文字/删除事务共存，修改后原 SPID 仍能删除。旧混合 run/超链接/动态字段及未 bundle tsx 回退定向用例通过。
- 测试中首次普通页面共存失败是 fixture 在同一进程多次解析产生临时 uid 与新进程 bridge 不一致；改为从真实 inspect 获取对象 id 后通过，没有为该测试改变产品身份规则。
- 独立 stdlib ZIP、lxml、python-pptx 回读源引擎产物：11 个文件部件身份集合不变，只 master/layout 两个目标部件改变，其他 9 个文件部件字节一致；新增框文字、几何、bodyPr 与删除 SPID 均核验。

本轮未运行或重复完整测试套件，未构建共享 static/dist，未提交或推送。所有产品文件冻结前身份见 `product-ready-sha256.json`。真实 HTTP/浏览器验收结果在下节单列，不能用本节局部测试或上一轮冻结资源替代。

## 本轮冻结与真实 HTTP 验收

本轮使用统一物理冻结 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113/source`。root 报告冻结 4283 源文件、104 后端基线文件，复制前后无漂移，构建/typecheck/四引擎 bridge/budget 检查均 exit 0。本专项不把构建报告替代为自己的完整测试运行。

实际运行身份：

| 项目 | SHA-256 |
| --- | --- |
| static manifest | `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650` |
| native.html | `53ca52500c63dd69d0bae839ed5c7aefbe144b664ac515bf894fd22bcd62e2c6` |
| edit-pptx.mjs | `e2ec1efca70c7195ed5b5c54ae66d71ecb209a2e94bb408ea3073184f836fc2c` |
| render-pptx.mjs | `2d3bca918a24430b102d7bb6367ce2679acf8c9fa730b36d67ea07dd6ddff13c` |
| SOURCE-SNAPSHOT-SHA256.json | `74e03133d91156fe3a379358f5a2c6bdd40962279be9682b35534cfccc6cfaa9` |
| 实际 source.pptx | `50f3a981e1b911eb523c8bceda60e3dbb16bde33e29d180db790b734db22c12d` |
| 实际 downloaded.pptx | `648a2497acd0ba0ca57c17b44a76998fe2ef66078bf2ed4012016c68f500a8d1` |

执行前已把 runner、三层 server/fixture 和独立验收脚本物理复制到证据目录 `harness/`，保存运行前 SHA。每次实际 runner/server 字节另存于 `browser-01/harness-snapshot/`、`browser-02/harness-snapshot/` 并与启动前 SHA 核对。browser-02 runner 为 `792cbdbcb4b9b6b29e5a17b4c47de6f90c568b38e35b2f0a3ef60ff1d745eb52`，独立读取脚本为 `35731533bd06b73fbb35f86adf62b7c494f754ffeab9f05325cfa514fbc54671`。实际生成 fixture 在导入前落盘 `fixture-before.json`，结束时核验并保存 `fixture-after.json`。本轮没有沿用上一轮静态资源或把后来脚本修改冒充实际运行版本。

`browser-01` 因运行前 live Python 与冻结基线有两项差异，在 server 启动前退出：0 导入、0 save、0 修订，证据保留为 `pre-server-stop.json`。这不是已完成保存的重跑。root 明确要求记录差异后继续，因此 `browser-02` 运行唯一完整保存：1 个 save 请求、1 个完成修订，修订号 2。浏览器实际加载 155 个唯一资源，均与物理冻结文件逐字节比对；入口为 `lazy-preload-helper-BPPmGX_j.js` 和 `lazy-unified-main-DK_7rZ5U.js`，无 pageerror、console error 或 HTTP 错误。

browser-02 实际覆盖：取消新增不写草稿；在真实母版部件新增框；保持 clientId 修改待新增框的文字、x/width；在真实版式新增后移除 pending；删除原版式 SPID 9002；同一 NativeDraft 的撤销/重做；两页继承渲染均包含新母版文字、保留原母版品牌、不含删除的版式品牌；刷新恢复草稿；390px 对话框无横向溢出；保存后修订重开，新增框已成为真实可选对象且不再是 pending、删除对象不再可选。已查看 `master-mobile.png` 和 `inherited-normal.png`，文字、表单及按钮可读，无裁切。

保存响应保持 `validation.ok:false`，具体原因为 `native_source_review_pending`；仍返回已登记修订和 PPTX 下载链接。下载 HTTP 200 且实际字节 SHA 与响应身份一致，没有把文件签发写成业务验收通过。独立 ZIP/lxml/python-pptx 回读确认：47 个非目录文件部件集合不变，只 `ppt/slideMasters/slideMaster1.xml` 与 `ppt/slideLayouts/slideLayout7.xml` 改变，其余 45 个文件部件字节一致；新增框实际文字、x=96/y=420/width=520/height=110（96dpi 像素对应 EMU）与 bodyPr 正确；删除的 SPID 不存在；两页原正文和讲稿保留。证据为 `browser-02/independent-verify.json`。

## Python 宿主身份的实际限制

Python 宿主仍为 `/home/junge/pros/smart_reporting`，不是隔离冻结执行。`browser-02/backend-before.json`、`backend-after.json`、`backend-finally.json` 逐文件保存 104 个文件的冻结期望 SHA 与实际 SHA，`backend-actual-changes.json` 为空，说明本次运行实际起止身份一致；不能写成“104 文件均与冻结基线一致”。两项已存在差异在起止均相同：

| 文件 | 冻结基线 SHA-256 | 实际运行起止 SHA-256 |
| --- | --- | --- |
| `smart_reporting/report_editor/render_preparation.py` | `82bb692e31a93b3bc840990b88f82fb67691631e812982fd670da4f6735c21a8` | `3dabe2d4c4bd92e65203303d503b63e4be44011059882dad2dbdc60282f7dd56` |
| `smart_reporting/report_editor/service.py` | `057713d398b9b28df955254842f7329a1012ffbf0b4abd0b71b312edc9423420` | `8a54ea38a759a2ff030957b68520eb0d8f59d2ca9fc97e2adf7919eb4a0e2f02` |

因此 summary 明确为 `frozenBackendBaselineAligned:false`、`backendActualStable:true`、`notClaimingPythonIsolation:true`。没有更新或覆盖旧冻结基线，也没有为这两项差异再次保存。15 个本专项产品/测试文件完成后与 `product-ready-sha256.json` 再次核对，无变化。

本轮结论仅为上述有限源能力与指定实际身份下的产品/HTTP 流程通过；不宣称完整 MasterView、业务事实或完整版式验收通过。
