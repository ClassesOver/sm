# 四格式续批：首字下沉、组合图、PDF 合并与母版文字增删（2026-11-13）

固定参照 `/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批复用三个同模型子 agent 并行，root 负责 Word 和统一冻结/独立复核。只关闭下列已验证子能力，整体穷举对齐目标保持 active；不是全量 Office 功能完成声明。

## 同一物理源码与构建

统一证据根 `/dev/shm/office-next-dropcap-combo-merge-master-elements-20261113`：4,283 份源码、104 份后端身份基线，`COPY-VERIFICATION.json` 确认复制前后无漂移。SOURCE 清单 SHA256 `74e03133d91156fe3a379358f5a2c6bdd40962279be9682b35534cfccc6cfaa9`；manifest `615163c4c3ded620bb13234122204fc6f4002f03c2c8079a1d1c444da6373650`；native.html `53ca52500c63dd69d0bae839ed5c7aefbe144b664ac515bf894fd22bcd62e2c6`。

前端 tsc、Vite、原预算与预算契约、四原生桥均 exit 0。预算脚本与前批逐字节相同，没有提高门槛。依赖链接将所有本地 workspace 包映射回物理快照；四桥 metafile 未发现意外引用 live 业务源码。既有打包告警保留，不写成零告警。

PDF 初始桥使用 root 通用 `createRequire` banner，与源码导入重名，首轮浏览器在 metadata 阶段失败，实际 0save/0merge。旧桥、metafile、原 pre-http 身份与失败日志保存在 `pdf-initial-banner-conflict/` 及 PDF `browser-frozen-01`。随后仅按仓库已有 package.json 的 `createBridgeRequire` 别名重建 PDF 桥，没有修改产品源码、前端资源或 SOURCE 清单。新桥 SHA256 `71031a5b456471902a0a5889f6527dd6e415ac77ce4d69f0462a2694804a304e`，七个最终 mjs 均通过 `node --check`。Word/XLSX/PPTX 已完成的保存没有重跑；PDF 在新桥上完成首次完整链。

## 本批已验证范围

| 格式 | 产品与真实链 | 实际下载及独立回读 |
| --- | --- | --- |
| Word | 固定源“无/下沉/悬挂”菜单、默认三行；顶层可编辑正文/标题/列表、新普通段落属性；与正文及段落格式组合；撤销重做、390px 菜单、草稿恢复，一次保存 4→5 后下载重开。 | 38,201B，SHA `270e909d471aba5a3e65bdfc2b4ea9a857ab2c078c067918de1843d2ca201b41`。两段 framePr 为 drop/margin、lines=3；人工 MANUAL/粗斜体、未知 pPr、标题/表/sectPr 及16个非目标部件保留。 |
| XLSX | 固定源 SelectData 逐系列 barChart/lineChart 与 secondaryAxis、增删重排、原生预览；四 family×axis 组、全局 idx/order、保留主轴；人工 J2/bold、390px 提交、UndoRedo、草稿恢复，一次保存4→5后下载重开。 | 6,900B，SHA `b15466d01595cb2bdf528bf4b12142ec3603e3da6208d9e9fa809cee9d6bc249`。openpyxl/lxml/ZIP确认 Added主柱/North主线/South次柱/Rate次线、缓存值、原主轴/title及非目标部件保持。 |
| PDF | 原 flush/确认/保存后，用新授权来源按用户列表追加多个外部PDF，生成独立派生文档；取消与未确认前0save/0merge，随后唯一一次4→5保存与一次merge POST；实际下载、派生6页重开。 | 3,931B，SHA `22d9df3f3ae456aa500f7535957a8b6f2340c078e6a2208b722e583ede7716c6`。pypdf确认来源倒序3/2/1，再B1/A1/A2，来源与合并标题均为实际已保存标题；原来源不被覆盖。 |
| PPTX | 原母版/版式部件内新增顶层文字框、改待新增文字/几何、移除pending、删原文字对象；沿同一草稿/历史/继承渲染/390px对话框/恢复，一次保存至修订2后重开真实对象。 | 48,179B，SHA `648a2497acd0ba0ca57c17b44a76998fe2ef66078bf2ed4012016c68f500a8d1`。47个非目录文件集合不变，仅master1/layout7改变；另外45个字节保持，新文字/几何与删除SPID、原正文/讲稿均核验。 |

四专项：[Word](NATIVE_WORD_DROP_CAP_ACCEPTANCE_20261113.md)、[XLSX](NATIVE_XLSX_COMBO_SELECT_DATA_ACCEPTANCE.md)、[PDF](NATIVE_PDF_MERGE_SOURCE_ACCEPTANCE_20261113.md)、[PPTX](NATIVE_PPTX_MASTER_ELEMENTS_ACCEPTANCE_20261113.md)。各自 RED/GREEN、原生协议、源实际行为和服务适配差异见专项，不用局部测试替代浏览器保存证据。

## 证据身份与不能扩大解释的边界

- 浏览器实际 JS/CSS：Word159、XLSX174、PPTX155 个不同资源；PDF128条响应、64个不同文件。全部与冻结文件 SHA 和 manifest/worker 引用关系匹配。Word/PPTX/PDF保留实际HTML身份；XLSX完整链没有保留原始HTML哈希，不据其它三者推定该回执存在。所有实际pageerror/console error/HTTP error集合为空。root已目视各专项桌面及390px截图。
- HTTP执行live Python，物理backend-baseline只是身份副本，不是隔离运行。Word/XLSX/PPTX各保留104文件实际before/after且起止相等；`render_preparation.py`、`service.py` 在运行前已与冻结基线不同，差异不被覆盖。PDF只核验9个明确签发链文件，九项与冻结基线匹配且起止稳定，不能泛化为全104文件。XLSX/PPTX第一次因两项基线差异停在server启动前，均0save；随后如实记录差异再完成唯一保存。生产数据库授权与完整业务流程未由这些替身宿主认证。
- 冻结时两份 LOCAL 登记有4个旧hash。live登记已更新；冻结SOURCE及旧登记未改，由 `LOCAL-ADAPTATIONS-RECONCILIATION.json` 逐项核验旧值、实际冻结源、新登记。不得把sidecar写成冻结原清单早已全部匹配，也不因此重构建/重保存。
- Word相邻 `docx-body-decorations.test.ts:52` 的一个旧断言仍失败，已在前批不可变源码复现。新增5例及段落20例、装饰另4例通过；未为求绿改旧断言。各专项定向测试通过与这项已知失败分别记录，未重复完整测试。
- root首次独立复核错误地把ZIP目录项当文件身份，误报PPTX集合不同，`root-verification-01.log` 保留；实际只新增16个目录条目，47个非目录文件集合相同。修正核验脚本按文件部件比较后，`root-verification-02.log` exit0，`root-independent-verification.json` 为 `ok=true`，再次独立回读四种实际下载文件。没有为核验工具问题改产品或重复保存。
- 所有保存和PDF派生回执保持 `validation.ok=false` 及具体review原因，真实身份可读文件照常签发链接；技术闭环通过不等于业务验收通过。

## 剩余范围与并发状态

首字下沉不覆盖任意嵌套/定位框；组合图本批只覆盖bar+line族，完整ChartPanels/细粒度series/point格式仍需逐项源核对；PDF合并沿源writer保留基文档结构，外部AcroForm字段树、目录、附件不保证完整迁移，数字签名有效性不保证，沿已有6MiB外部上传传输边界，超过24MiB的实际结果仍签发下载但不在线重开。PPTX部件内顶层对象增删不等于完整MasterView，现有对象任意变换/填充/描边等仍未完成。

固定源MasterView并没有创建/删除母版或版式部件的入口，且不进入组内对象；因此旧表里的这些条目只能作为产品边界，不能继续冒称为已经确认的GenOffice入口缺口。完整源等价、四格式AI任务与生产授权仍需独立完成。

并发工作已在本批之外推进仓库HEAD至 `1138887df2541b748ebe5746871e4198bb48a712`，本批没有再次pull、提交、推送或部署；不把最初已完成pull时的6a713d05写成当前HEAD。实时源码、审计文档与管理界面仍可能继续变化；只对 `root-independent-verification.json` 的具体采样及冻结身份下结论，不覆盖并发改动或追赶重建旧批。
