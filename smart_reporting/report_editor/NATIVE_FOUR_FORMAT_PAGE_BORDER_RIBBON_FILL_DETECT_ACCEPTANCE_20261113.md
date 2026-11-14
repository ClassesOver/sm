# 四格式页面边框、Ribbon命令、母版填充与PDF字段检测（2026-11-13）

固定参照为 `/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批在 Word、XLSX、PPTX、PDF 各完成一个限定的真实源入口能力；这不是全格式对齐完成声明。原产品、测试和本批文档改动均在共享工作区，未提交、推送或部署。

| 格式 | 本批范围及专项记录的 HTTP 结果 | 明确未覆盖 |
| --- | --- | --- |
| Word | 当前节“页面边框→方框/无”复用 `setSectionLayout`、NativeDraft、UndoRedo 与源分页预览。专项记录一次4→5保存，下载38156字节，SHA `7186a44990d7573d088a1de7ecaa033bfae4e70d87d425de9326b6df6db134a8`；独立回读记录defaultBox/none、人工正文格式和16个其它部件保留。见[Word专项](NATIVE_WORD_PAGE_BORDER_SHORTCUTS_ACCEPTANCE_20261113.md)。 | 完整边框和底纹对话框、艺术边框、任意边宽/颜色/应用范围及普通连续画布的边框层。 |
| XLSX | Ribbon真正接通“删除图表”和“合并工作簿”。专项记录明确删除第二张同名图、保留第一图及锚点、Undo/Redo；合并取消/草稿恢复/导入值样式几何均通过。唯一一次4→5保存，下载7186字节，SHA `0aacda563834507689207d7ee630b63386bfa0cac343d813a81049e066789b2a`，独立openpyxl/lxml/ZIP回读通过。见[XLSX专项](NATIVE_XLSX_RIBBON_DELETE_MERGE_ACCEPTANCE.md)。 | 删除通用drawing对象；合并只覆盖既有值、部分样式与表格几何，不迁移完整OOXML、图表、图片、宏、透视表或外部连接。可信公式缓存导入为值，不保留公式引用图。 |
| PPTX | 已有母版/版式顶层对象支持实色与none填充；填充能力与文字编辑能力分别判断。专项记录唯一保存至修订2，下载SHA `661a85f620b5a8d13a9f9907dbd29743784c964c8f85844b7e491942013c1560`；47个文件部件仅master1/layout7变化，其余45个逐字节保留。见[PPTX专项](NATIVE_PPTX_MASTER_FILL_ACCEPTANCE_20261113.md)。 | 复杂/继承填充的重写、组内对象、源没有的母版/版式部件创建删除入口，以及完整MasterView。 |
| PDF | 从原生页面文字/下划线/线段作确定性字段候选检测，逐项确认后复用既有单字段创建草稿。专项记录一次4→5保存，下载3371字节，SHA `0d8ea293d140442b8fb286905d07b36ecc3dc15073159ac35ac7bbf0f690ff1d`；pypdf独立回读为两页、单个name字段、第一页矩形`[100,439,260,457]`及控件appearance。见[PDF专项](NATIVE_PDF_FORM_DETECT_SOURCE_ACCEPTANCE_20261113.md)。 | 一次批量原子创建多个字段；签名候选不支持加入草稿。检测不使用AI/OCR，也不替代完整静态表单绘制/编辑能力。 |

四项专项均记录 `validation.ok=false` 与 `native_source_review_pending`，同时签发已核验身份产物下载；没有标记业务验收通过。Word/XLSX/PPTX各105个后端基线文件的真实live执行前后身份相同，且相对冻结基线存在 `native_pdf_contract.py` 与 `delivery/docx_native.py` 两项既存差异；PDF只核对九个命名签发链Python文件。后端快照仅为身份基线，不表示隔离执行。XLSX完整保存记录未保留HTML哈希，不在此推定。

统一冻结快照记录4318份源码，manifest SHA-256 `5ede4bf0e2689e7427f0e90ea296a912ae56aa4ef124be01a1916d8af55c3c90`，native.html SHA-256 `4222b799ff100e13b4d9b8f44be2c883c28d08732e55acc3bfb60affa3d3d493`。Vite、四桥、原构建预算及预算合同记录通过；初始类型检查曾因并发slides-media类型错误退出2，随后一行纯类型注解在冻结与live分别修补，esbuild转译后JS字节等价，冻结类型检查复验退出0。构建预算未提高。复制期间smoke runner变化及实际执行新版runner已分层记录，没有冒称冻结旧runner被执行。

**复核限制：** 专项最终报告保留了下载、回读、资源身份和截图结果，root曾查看本批PDF、PPTX、XLSX的截图。随后尝试独立执行汇总核验时，本批统一快照目录和四份专项`/dev/shm`证据目录均已不在当前文件系统，只有核验脚本仍在；因此本文件不宣称root独立复验成功，也没有重跑已成功的完整保存来重造产物。专项结果及对应下载身份按各专项原始记录引用，当前无法从临时目录二次读取。完整四格式穷尽对齐目标保持active。
