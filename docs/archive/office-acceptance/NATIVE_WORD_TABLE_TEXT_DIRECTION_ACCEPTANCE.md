# Word 表格文字方向验收记录

本项已完成下述专项验收，全量目标仍开放。固定来源 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；三个入口、真实源命令及aliases调查见 `NATIVE_WORD_TABLE_TEXT_DIRECTION_INVESTIGATION.md`。

## 已接入契约

严格setTableCellTextDirection绑定来源block/hash，步骤恰为top/left/bottom/right/direction五字段，1–50步。lrTb清除直属方向标记，tbRl/btLr写入；矩形触及逻辑slot后去重owner，合并owner和物理continuation同步，未选owner即使continuation原方向不同也保留原字节。有效来源tbRlV/btLrV由真实parser归一为tbRl/btLr；未知/重复/嵌套方向及额外属性拒绝。

前端投影、collector及草稿恢复共用同一core，比对完整来源网格/方向及最终table，禁止同表文字/格式/其他结构混编；无需像素normalize。方向无节宽依赖，可与独立页面设置同批。保护/hash校验、只改直属textDirection XML、实际保存回读及metadata保留已接入，不重建段落、宽度或高度。

## 当前证据

- core3、bridge初4及未选合并owner追加1通过，限定types通过，见 `/tmp/cell-direction-*.log`；均先在缺模块处RED。
- UI首5及反向混编/新表/无表追加1通过，最终类型检查进行确认；未构建或重复完整测试。
- Python先RED缺capability，最终6项 `/tmp/word-cell-direction-python-green.log`通过：三方向多次保存重开/clear、原段落与非目标部件、非法字段/矩形、触合并下半slot修改所有物理continue、伪造hash/保护及独立页面设置混批。
- bridge `/tmp/word-cell-direction-bridge-build.log` exit0。独立复核与最终built资源验收待补。

最终前端types `/tmp/word-cell-direction-ui-types.log` exit0，生产冻结，统一build `/tmp/office-cell-text-direction-build.log`执行中。独立只读review真实DOCX探针 `/tmp/word-table-direction-investigation/review-geometry.log`确认嵌套伪造几何/方向属性拒绝，无关tcW属性、原段落方向、行高与宽度原样保留；未重跑已有绿套件。

统一build终态exit0（41.41s），同前缀budget与budget-contract exit0，未提高预算。4242真实浏览器专项已启动，覆盖普通/alias合并/缺tcPr三来源与三个方向逐修订保存，并检查实际文本字符轴向。

## 最终浏览器验收

`/tmp/word-cell-direction-built-smoke.log` 首轮exit0、ok=true/errors=[]，Chromium140.0.7339.16；三来源×三方向共9次实际保存/HTTP下载/ZIP/明确新修订重开通过。产物 `/tmp/docx-cell-direction-built-p1RPVx`。普通、alias复杂合并/隐藏continue及缺tcPr来源分别验证90/270/水平，computed writingMode为vertical-rl/sideways-lr/horizontal-tb，真实文本Range字符分别沿Y正/Y负/X正方向推进。

Undo/Redo与draft、alias归一、所有physical continuation同步、horizontal删除及缺tcPr插入均通过；脱敏直属textDirection后完整document.xml逐字相同，其他OPC部件与cell身份保持。120个JS200/SHA核对，root目视revision-12-direction-reopened.png确认合并单元格真实旋转且其他格横排不变。

授权/修订替身路由不代表生产HTTP或桌面Word/PDF排版等价。表格九宫格对齐、属性和边距等仍为独立待办；全量Word/XLSX目标保持开放。
