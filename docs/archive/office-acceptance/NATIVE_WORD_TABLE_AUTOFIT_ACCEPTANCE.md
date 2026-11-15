# Word AutoFit 三模式验收记录

本项已完成下述专项验收，全量Word/XLSX目标保持开放。固定来源 `f8c17004fb730df11f0f743164ffd8b4281bb38c`；源命令、真实DOCX探针与局部精度适配见 `NATIVE_WORD_TABLE_AUTOFIT_INVESTIGATION.md`。

## 已实现契约

三个Ribbon入口共用严格 `setTableAutoFit` 操作与有序 `{mode:'contents'|'window'|'fixed'}` 步骤，最多50步，不接收客户端最终XML、网格或节宽。整个来源表修改，保留完整步骤，不折叠成最后一个模式。已有fixed、auto、百分比及省略首选宽度/单元格宽度的来源使用独立准入，不依赖列宽编辑的fixed-dxa能力。

初始normalize只恢复可信整数twip对应的cell.colwidth，保留来源模式、百分比和其他显示属性；baseline前执行，不产生编辑意图或历史，草稿从原baseline按同一core恢复。直接fixed/window保持奇数整数网格，contents清除显式网格投影后保存遵循来源默认9360网格，连续切回fixed遵循来源节宽fallback。仅fixedGridWidths闭包逐字摘录；其他为等效投影，不宣称整个源command原样迁入。

bridge只补直属tblW/layout/gridCol/tcW，合法合并及隐藏continuation原内容保持；保存后回读实际模式/宽类型/值/grid/物理tcW与单元格身份。实际单栏节宽由服务端推导，保护、hash、同表混编及同节页面布局依赖保持严格校验；多栏及不清楚几何仍只读。

## 当前针对性证据

- 核心3项、bridge初4及插入顺序/独立raw模式/回读加强追加项通过，限定类型检查通过。源nil/pct0/pct7500/dxa0模式与真实parser对照通过，未重复完整测试。
- UI首4、collector/replay与直接fixed精度追加2、readonly/新表/嵌套/无表等追加项分别通过；Ribbon pressed状态及最终类型检查通过，见 `/tmp/word-autofit-ui-*.log`。
- Python先RED缺 capability，最终7项 `/tmp/word-autofit-python-green.log`通过：三模式连续保存重开保段落和其他部件、非法steps、真实第二节6400twip回退3195×2、客户端伪造节宽、同节布局混编、hash/保护及多栏边界。前端同节依赖契约1项 `/tmp/word-autofit-section-contract.log`通过。
- Bridge构建 `/tmp/word-autofit-bridge-build.log` exit0。

独立review新增12个pct50/省略宽度来源的有序步骤探针，前后端core与bridge最终网格/模式一致。发现前端全局分节混批限制比服务端更严，误拒另一节独立分节；已给全部来源块签发sourceSectionId，并仅对AutoFit用此身份区分同节/异节，缺身份时继续拒绝。前端先RED后GREEN `/tmp/word-autofit-cross-section-{red,green}.log`；实际Python正反顺序混批均保存3节且模式正确，1项通过 `/tmp/word-autofit-cross-section-python.log`。当前bridge `/tmp/word-autofit-section-bridge-build.log` exit0，旧列宽/行高分节边界保持原样。

## 待补最终证据

独立复核前后端来源投影一致性，统一最终前端构建及预算，真实公开Ribbon/UndoRedo/草稿/三来源与复杂合并/实际保存下载重开/完整非目标XML和OPC部件字节对照。生产HTTP、桌面Word或PDF排版等价尚无此项证据。全量Word/XLSX目标保持开放。

2026-11-10 双方生产已冻结，统一构建 `/tmp/office-autofit-goto-build.log` 正在执行。最终probe增加100%window来源，70%pct来源严格按source parser有效模式contents处理而非误标window；仍保70%原属性直到用户明确切换。复杂merge/隐藏continue及缺tcW来源inspect预检可用，不将预检当built验收。

统一build终态exit0（40.76s），同前缀budget与budget-contract exit0。AutoFit与goto strict built分别在4242/4243并行运行。独立review另5个几何探针确认未知/嵌套伪造宽属性被拒、合法嵌套表111twip不污染外表contents的9360网格且嵌套XML逐字保留；未改生产或重跑已有绿测试。

## 最终浏览器证据

`/tmp/word-autofit-built-smoke.log` 首轮exit0、ok=true/errors=[]，Chromium140.0.7339.16，120个加载JS200/SHA核对。产物 `/tmp/docx-autofit-built-Mw4BvQ`。13次公开保存→真实Python patch→实际HTTP下载→ZIP→明确新修订重开通过。

来源覆盖fixed、contents、70%pct且缺tcW、复杂横纵合并/隐藏continuation及100%window；直接fixed保留奇数网格1801/2401/3001。各来源依次contents→window→fixed保留完整steps，Undo/Redo与草稿恢复通过，保存最终网格3000×3；另逐修订分别保存contents/window/fixed，验证每个最终模式。仅脱敏四类直属几何标签后全document.xml逐字相同，其他OPC部件字节和逻辑/物理cell身份保持。root目视revision-32-autofit-reopened.png，复杂合并内容及布局正常。

授权/修订路由仍为替身；未据此声称生产HTTP、桌面Word或PDF布局等价。字面百分比宽（如50%字符串）、缺grid、浮动/RTL及修订几何等来源边界仍见调查文档，未把这些只读来源计为已覆盖。
