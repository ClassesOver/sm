# Word 所选单元格自动换行 built 验收

```bash
node smart_reporting/report_editor/frontend/smoke/docx-table-cell-wrap-built-smoke.mjs
```

独立默认端口4267，可设 `DOCX_CELL_WRAP_SMOKE_PORT`；`DOCX_CELL_WRAP_START_REVISION`仅续未通过来源；`DOCX_CELL_WRAP_RESUME_DIRECTORY`可指向上一产物目录，读取已完成source result并核验下载SHA、复制DOCX后直接复用，绝不重复已通过保存。只启动vite preview，不build；等待root统一dist放行。统一dist与预算正式放行后，已完成四来源built验收，结果如下。准备夹具 `/tmp/word-cell-wrap-built-prepared.docx` 的capability=true，physical noWrap为[true,false,false,false]，hidden continuation存在。

限制为四来源、四次真实保存，不重复旧边距、行跨页或对齐专项：

| 来源修订 | 真实选择及最终动作 | 物理目标结果 |
| --- | --- | --- |
| 1 ordinary auto | 单格caret关闭自动换行 | [true,false,false,false] |
| 10 fixed/mixed | 鼠标首行矩形，从mixed统一开启 | [false,false,false,false] |
| 20 RTL auto | 鼠标首行矩形关闭 | [true,true,false,false] |
| 30 merged | 鼠标点击跨两行owner的可见下部，开启 | [false,false,false,false] |

merged的鼠标点击仅证明跨行owner下部的真实caret操作，不能证明独立TableMap lower逻辑slot；该归一由source专门PM单测覆盖，不注入浏览器选区冒充UI路径。所有物理cell含tcFitText及未知sibling，merged continuation有独立隐藏正文与false noWrap；保存须同时映射owner/continue且保留隐藏正文、tcFitText、整数grid2001/1999及全部非目标字节。

每源先通过既有table-properties→cell-wrap公开导航确认原值/混合indeterminate、aria-checked=mixed，未触碰确定保持完整DOM。每次改值后Undo/Redo，再连续往返一次取最终值；仅setTableCellWrap.steps，不开放通用tcPrEdited。刷新草稿后恢复同种公开选区，再比较完整canonical DOM（仅属性和class token排序、不删selection marker）及实际表格/单元格尺寸、正文和white-space。保存通过真实Python patch，HTTP下载SHA必须匹配实际保存字节，ZIP仅mask直属noWrap后完整document.xml与全部physical cell XML、其它ZIP部件保持。非目标cell noWrap精确不外溢。明确新修订重开后live/draft/reopen实际geometry与CSS一致，留截图/HTML及即时source result，后续失败不丢已过证据。

auto/fixed均记录真实尺寸与换行CSS。固定布局或超宽表格可能在noWrap=true时仍按可用宽度换行，本专项不承诺视觉永不换行、不改列宽/AutoFit/tcFitText；四来源含fixed真实分支，超宽仅是UI范围说明，不能声称已经真实超宽fixture验收。不会为得到视觉变化调整字体或宽度。

成功输出含四operation、下载SHA、实际geometry、所有加载JS的HTTP200+本地SHA及console/pageerror=[]；失败保留failure.html/png和stage。授权路由为本地夹具，保存是项目真实DOCX patch，下载是真实HTTP；不宣称生产授权HTTP、桌面Word或PDF等价。此次仅运行新dist专项，未运行旧dist或完整测试。

## 本次实际结果

2026-11-10，Chromium `140.0.7339.16`，默认4267端口，首次执行4/4通过、恰好4次保存，无重跑。日志 `/tmp/word-cell-wrap-built.log`，结构化结果 `/tmp/word-cell-wrap-built-manifest.json`，产物及逐来源checkpoint `/tmp/docx-cell-wrap-built-X2U2pO`。

| 来源 | 下载修订 | 下载SHA256 |
| --- | --- | --- |
| auto-caret | 2 | `0eda252016f2930ab014c2b23a5b8384db3f6074242d864831894b3ed359d3af` |
| fixed-mixed-rect | 11 | `3e3eabd6407714b24308fd9bf49096a63409d014342338f9a3ecc9c38bee48ab` |
| rtl-rect | 21 | `b55cfdc7b06c79d872aed6fcf0efb6057e83159864169592d07a7b5d641618b8` |
| merged-lower | 31 | `e0f7f7d09af96fc118fa7329e984ac4507b9571abb75bc0f023cf366761089b8` |

四来源的未触碰/mixed、Undo/Redo、连续往返、草稿恢复、真实Python保存、HTTP下载回读、明确新修订重开全部通过。直属noWrap之外的完整document.xml、全部physical cell XML及其它ZIP部件一致；保存后physical flags与上表预期一致。实际geometry、CSS white-space与正文在live/draft/reopen间一致，merged重开截图已目视检查。

121个实际加载JS均HTTP200且与本地dist SHA一致，console/pageerror均为空。主要构建身份：

- `lazy-docx-main-B2BZ7BLD.js`：`ddcd80cb77eeff4b6fb150868cf857d5f550f7a7e828521a956577cec192165f`
- `lazy-native-docx-engine-C7gMc9rN.js`：`5da009cd517635838dd7c91210647148af3cf61d73c83fba18af5f96d4fd0612`

上述本地授权路由、merged下部caret及未验收超宽/桌面Word/PDF的覆盖边界保持适用。
