# PDF 表单多页选区按页独立排列

固定源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 范围与源码依据

- `apps/pdf/src/renderer/App.tsx:4113–4123` 的 `arrangeSelected` 先按 `pageIndex` 分组，每页独立取首项 anchor、独立使用该页显示坐标；每页不足两个不处理。
- `App.tsx:4161–4199` 的分布分支每页不足三个不分布（源随后回写原矩形）；本地直接不写不足组，以免无意义重绘。
- 复用已有全部十一种排列：left / centerH / right / top / centerV / bottom / distributeH / distributeV / sameWidth / sameHeight / sameSize；未增加源不存在的跨页统一 anchor、换页或组拆分。
- 请求仍为一个原有 `arrangeFormWidgets`，全局最多 64 个控件。来源 SHA、全部目标四重身份、重复项、未知键、只读资格先完整校验，再分组。UI 还在分组前检查每个选中控件所属页面及原区域，包括最终跳过页面。
- 对齐/尺寸每页至少两个，分布每页至少三个；不足组保持不变。没有任何满足数量条件的页面时明确拒绝。已对齐的有效页面继续允许原单页 no-op 行为。
- 各页独立使用 CropBox / Rotation；绝不共用跨页 anchor，不改 `/P`、页面 Annots 或 Widget 页归属。
- UI 按钮选项标明实际页号，并说明“按页独立排列”。

## 保真修复及边界

原 `applyFormWidgetEdits` 修改 rect 后将整个字段标 dirty，`save(updateFieldAppearances:true)` 因此会重绘同字段未操作或跳过页面的兄弟 Widget。真实失败：共享字段跳过 Widget 的 `/AP /N` 从 `36 0 R` 变为 `44 0 R`，即使该 Widget 的 Rect 没变。

仅排列路径使用 `writeWidgets(..., preserveUntouchedWidgets=true)`：

1. 记录所有原始对象及未修改 Widget 的原 `/AP`；只有实际发生矩形变化的 Widget 才列入修改集合。
2. 正式更新前浅复制 `/AP` 顶层字典，防止 pdf-lib `PDFAnnotation.setNormalAppearance` 对原字典原位写入。保留原始流和原间接字典。
3. 继续正式 `updateFieldAppearances()` 重绘修改 Widget，恢复所有未修改 Widget 的原 `/AP`。
4. 只调用一次 `save(updateFieldAppearances:false)`。属性编辑原路径保持原行为。
5. 写后除既有正文/Annots/字段结构检查，还逐个复读全部原始间接对象。只允许实际修改 Widget 的 `/Rect` 和 `/AP` 变化；其余原对象、原流字节必须保持。新生成的 AP/font 对象可能存在，**不承诺对象数量零增长，不清理新增孤立对象**。
6. 后置复核失败保留实际 bytes、SHA、size，以 `pdf_form_widget_output_review_failed` 返回失败回执，不假报通过。

不包括 OCR、数字签名/XFA、跨页移动、画布拖动及新的字段属性。

## 专项验证记录

证据目录：`/tmp/pdf-next-multipage-arrange/`。

- `native-red.log`：新增 4 项真实失败，原因是旧跨页拒绝；初始 fixture API 拼写错误已修正，不计入真实 RED。
- `ui-red.log`：新增 2 项真实失败，分别是旧跨页拒绝及面板缺少按页提示。
- `native-preservation-probe.log`：最小分组后 3 PASS / 1 FAIL，明确捕获共享字段跳过 Widget AP 被改写。
- `native-shared-object-probe.log`：证明仅保存原 AP 对象再恢复不足，顶层字典被库原位改写；由此采用更新前浅复制。
- `native-shared-green.log`：仅重跑原共享字段失败项，1 PASS。
- `native-save-raw.log`：新增单次保存/后置故障回执，以及间接共享 AP 原字典/流保持，2 PASS。
- `native-affected-green.log`：保存路径改变后，仅重跑受影响原先 3 项，3 PASS。包含所有十一种排列、每页不同尺寸/CropBox/旋转、跳过单例页、分布跳过双控件页、跳过目标的四重伪造身份拒绝、全组不足拒绝、旧单页排列。
- `ui-green.log`：最初 UI 2 项 PASS，含真实面板暂存和 Undo/Redo。
- `ui-skipped-page-red.log` → `ui-skipped-page-green.log`：新增只移除跳过单例所属页面的回归，1 FAIL → 1 PASS；没有重跑已通过 UI 项。
- 原 `bridge/form-design-safety.test.ts` 的“两页各一控件”案例仍应拒绝，只把断言从旧“同一页”改为新“每页数量不足”，尚未重复执行该旧专项。
- `node --check smoke/pdf-form-multipage-arrange-smoke.mjs` 与 Python `py_compile` 通过。

### 独立 pypdf 原生复读

独立生成了三页真实 PDF（不同旋转、CropBox），共享文本字段跨页，原 AP 字典间接化并被共享；通过真实排列函数生成后用 pypdf 独立核验（不是 mock）：

- 输入 SHA：`110f928e32508bb5239abd1744b0f7b31902ce2e72a995b0855a34b4aa9ef875`
- 输出 SHA：`d03fd10b34cdfce82a448f77f1c663ef76de4d131e8e7090922ae429e28a438b`
- 输出 size：9241 bytes；应用索引 `[0]`。
- `independent/pypdf.json`：PASS；3 个页面组，2 个实际变化 Widget，复核全部 34 个原始对象及 raw/decoded 流，独立验证 sameSize 页内 anchor、原树/页归属、正文、Annots 以及跳过共享 Widget AP。

## 浏览器验收脚本

专属脚本：`frontend/smoke/pdf-form-multipage-arrange-smoke.mjs`，独立复读：`pdf-form-multipage-arrange-verify.py`。本子任务未自行构建或打包；以下初始交付之后，root 已对统一冻结资产执行真实浏览器验收，结果见后文。

```bash
PDF_SMOKE_STATIC_DIRECTORY=<统一冻结的静态目录> \
PDF_FORM_MULTIPAGE_SMOKE_DIRECTORY=/tmp/pdf-form-multipage-browser-20261111 \
PDF_FORM_MULTIPAGE_SMOKE_PORT=4349 \
node smoke/pdf-form-multipage-arrange-smoke.mjs
```

- 基于既有 `pdf-form-create-server.py`，真实 grant/cookie/CSRF/生产静态资源/preview/save/publication/download/reopen。
- 真实 UI 分别在第一页建 a/b、第二页建 c/d、第三页建 singleton；每次保存独立预览确认、下载核 SHA/size，再重开。
- 真实跨页全选五控件做 left 与 sameSize，两个页面独立 anchor，第三页单例保持；left 同时核 Undo/Redo。
- 独立 pypdf 对两次排列逐一核算矩形并检查全部原对象及流（仅实际变化 Widget Rect/AP 例外）。
- 每个实际 save 立即写 `checkpoint.json`（即使后续 download/reopen 失败也不重复保存）；下载核验后继续记检查点。每个 JS asset 的磁盘/响应摘要也落入同一检查点。
- 失败时保留源 server，使用相同目录、端口、冻结资产重跑，从最新成功 save 的实际 openUrl 续跑；核验 server 保存数、输入 SHA、已下载文件摘要、冻结资产摘要，不重做已过 UI 保存。若 server 已失效，明确拒绝自动重放已完成保存。
- 成功后关闭自己启动的 server。若手工停止失败残留 server，PID 在 `checkpoint.json` / `failure.json`。

## 生产冻结

仅两项生产文件；root 负责共享桥接/HTTP、统一 build、资产与包登记：

| 文件 | SHA-256 |
|---|---|
| `reporting/pdf_engine/bridge/form-design-properties.ts` | `3134e84edc4ce27c620f69c7b61285e06ac2bdc2d1f041024725177553007667` |
| `report_editor/frontend/src/pdf-form-create.ts` | `167dae320cfc6cb395a77538432170b2856ba8986258536d9d2b15924b3e0773` |


## root 统一冻结资产的真实浏览器证据

证据目录：`/tmp/pdf-ap-arrange-links-form-browser/`；实际 `summary.json` 和七个 `*-downloaded.pdf` 已由子任务只读复核，文件 SHA/size 与保存回执一致。

- 静态目录：`/tmp/pdf-ap-arrange-links-static`。
- manifest SHA：`8c79637a9733aeefbbd248d7754b9fcc9b0b898bf5144c2c81078eda83519451`；37 个实际 JS asset 的响应/磁盘摘要核对通过。
- Chromium：`140.0.7339.16`。
- 原始来源 SHA：`6467d9835f999c4efcad36eb520dc0344ac5b2866d792d97a4505e17a361dc31`，`sourceUnchanged: true`。
- 真实七次保存：a / b / c / d / singleton 创建，以及 left / sameSize 排列；revision 4→11，parentRevision 连续，七项均 `downloadVerified: true`、`reopened: true`。
- 真实三页全选按页独立排列，第三页单例保持；left 的 Undo/Redo 路径已由 smoke 验证。
- `pageErrors` / `consoleErrors` / `httpErrors` / `assetErrors` 均为空。
- 七个保存回执仍如实报告 `validation.ok: false`，原因均为 `native_source_review_pending`（原生编辑内容尚未重新核验业务事实与完整版式）；保存、实际下载和新 revision 重开均正常。**浏览器技术专项通过不代表业务/完整版式验收通过。**

| 排列 | revision | 实际下载 size | 实际下载 SHA-256 | 独立复读 |
|---|---:|---:|---|---|
| left | 10 | 10643 | `181f9212f103e530e73801d5400d0ce4ceb09c1de79db8b20dbe61f5ff6a2343` | 47 个原对象；2 个实际变化 Widget；3 页独立分组 |
| sameSize | 11 | 11520 | `274214dcc898bb748f4b20a86a4616cdf7950aa8ab1e9381b6d4341b6298e17d` | 50 个原对象；2 个实际变化 Widget；3 页独立分组 |

两次独立 pypdf 复读均通过原未操作对象与 raw/decoded 流、字段树、Annots、页归属和页内矩形计算检查。只对实际变化 Widget 的 Rect/AP 作例外，未承诺对象数量零增长。

root 已生成 `final-render-1.png` / `final-render-2.png` / `final-render-3.png`，本次仅核对 summary 和下载身份，不代替 root 的页面目视验收，也未新增任何测试或浏览器重复运行。此补充只改本文档，生产冻结保持。

最终 root 目视已完成：实际 sameSize 下载的三页 Poppler 渲染确认前两页分别对齐/同尺寸，第三页单例保持原位。第三页窄控件的既有长文本仍裁切，未将其保持原样冒称溢出修复；完整表单视觉保真不由本项推断。统一证据见 NATIVE_PDF_AP_ARRANGE_LINKS_ACCEPTANCE.md。
