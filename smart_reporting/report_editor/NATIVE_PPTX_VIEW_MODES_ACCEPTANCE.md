# PPTX 普通/幻灯片浏览视图接入验收（2026-11-13）

固定源：`/home/junge/pros/genoffice-source-full`，commit `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次未重写共享构建、static/dist、SOURCE、hash或总审计。

## 源映射与接入设计

- `App.tsx:551` 的 `viewMode` 与 `App.tsx:2090` 的 `onViewMode`：普通/排序视图为UI状态，切换清对象选择与编辑。本地仅启用 Normal/Slide Sorter；Normal恢复现有普通编辑器。
- `App.tsx:2170–2325`、`3753–3790`：排序视图的真实缩略图、click/Shift/Ctrl选择、横向中点落位整块拖排、双击返回Normal。本地复用当前 `renderTree`、来源页ID、`order` 和 `NativeDraft`，未另建文稿或历史体系。
- `SlideThumb.tsx`：原字节复用，SHA256 `79f845305e3297b5500772f01769a452c9a348bd8c1242c537772cf7a907aaaa`，与主画布共用StaticNode。
- `shared/slide-selection.ts`：原字节复用，SHA256 `d25f417d8d4a5537268bd7837fa1406718c54719326eecfc58730681f3e514f8`。
- `use-visible-thumbs.ts`：原字节复用，SHA256 `ca7a222d87b030b80bb16296b1eaa9fb93aa55c59c27b5af6a07f8740d999e7a`。沿用可见区域懒绘制，远离视口的缩略图保留同尺寸占位。
- `keyboard-actions.ts:315–401`：焦点内Ctrl+A、Up/Down/PageUp/PageDown、Home/End、Shift+Home/End、Delete/Backspace；本地保留IME/已处理事件/输入控件边界。Delete整批仅一个草稿历史，至少保留一页；不支持安全删除的草稿页返回现有软提示。
- Ribbon 源 `IconPrintLayout` / `IconArrangeAll`，两个入口使用实际互斥aria状态。

全部证据根目录：`/dev/shm/office-slides-view-modes-20261113`。下文相对证据路径均以此为根。

## 验证结果

- RED：`red.log`，原始Normal按钮disabled导致明确行为失败。
- GREEN：`green-01.log` 中原37项Ribbon与4项视图集成通过，唯一新增入口断言误用了无参数按钮而不是toggle回调，修正测试为既有 `onAction(command,true)` 后 `green-ribbon.log` 通过。
- 最终产品：`green-final.log` 的4项视图集成与入口共5项通过；后补备注IME定向测试在 `notes-ime-final.log` 通过。未重复完整测试套件。
- `tsc-final.log`：frontend `tsc --noEmit --pretty false` 退出0，无错误输出。
- `browser-03/summary.json`：真实源码Vite、实际HTTP导入/授权/预览/保存/下载/修订重开链。107个JS/TS资源，浏览器、console及HTTP错误均为0。
- 实际缩略图为两张208×156画布，各179个深色内容像素；已视觉查看桌面/390px截图。像素计数仅作为实际绘制和非空内容证据，不声称完整文稿排版验收。
- 实际交互：Shift/Ctrl多选、Home/PageDown/Ctrl+A、IME边界、双击Normal、当前页保持、未失焦备注切换保持；真实鼠标拖排到 `[1,0]`，Undo/Redo和刷新恢复；390px无排序区横向溢出。
- 实际保存恰好1次；下载SHA256：`70dddfb33af981559c9d512fb5bcdeb618b03f3e3009af485852cdd76fff58a5`。
- `browser-03/independent-readback.json`：独立python-pptx+ZIP回读确认正文按原页2、原页1排列；备注修改仍绑定原页2；仅 `ppt/presentation.xml` 与 `ppt/notesSlides/notesSlide2.xml` 改变，其他45part原字节保持，无新增或删除part。
- `final-lazy-readonly/summary.json`：在最后接入源懒绘制后，用上述实际下载文件重新真实导入，只读续验桌面/390px画布与全部选择/键盘切换。108个源码资源，零浏览器/console/HTTP错误，零额外save。
- `product-source-snapshot.json`：最终源码身份快照。

## 边界

- Normal复用现有普通编辑器（现有侧栏仍为文字页签与已有操作）；未在本次改造普通视图侧栏为源缩略图轨道。
- 本次未扩展Outline、Reading、Slide Master、源桌面幻灯片clipboard和context-menu IPC。排序视图不会把Ctrl+C/X/V误送到对象剪贴板链；这些桌面操作未标记为已支持。
- 新建/复制页缩略图沿用现有主画布的来源/版式投影；待保存结构对象仍遵守现有预览边界。未声称全部待保存结构内容已在缩略图中完整渲染。
- 发布验收仍明确 `validation.ok=false` / `native_source_review_pending`。已生成并核验身份的PPTX照常签发下载链接，不标记业务事实/完整版式验收通过。
- 未改变公式默认居中叠放行为；本夹具正文含“公式验收”字样仅因为复用了真实HTTP夹具，不代表本次验收了公式排版。

## 最终冻结 minimal 续验

`frontend/smoke/pptx-view-modes-smoke.mjs` 支持 `ASSET_ROOT` / `ENGINE_ROOT`（也支持 `PPTX_VIEW_ASSET_ROOT` / `PPTX_VIEW_ENGINE_ROOT` 与既有宿主变量）。指定冻结资源根目录后不启动Vite，强制只读minimal模式；必须同时提供已保存真实文件的 `PPTX_VIEW_REOPEN_FILE`，缺少时立即失败，不能回退到HTTP保存流程。冻结模式必须指定现成引擎根目录，不触发引擎构建。

统一构建最终身份确定后，已使用以下参数完成只读续验：

```bash
cd /home/junge/pros/smart_reporting/smart_reporting/report_editor/frontend
TMPDIR=/dev/shm \
ASSET_ROOT=/dev/shm/office-four-format-source-library-20261113/static \
ENGINE_ROOT=/dev/shm/office-four-format-source-library-20261113/source/smart_reporting/reporting/slides_engine \
PPTX_VIEW_EXPECTED_MANIFEST_SHA256=845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c \
PPTX_VIEW_REOPEN_FILE=/dev/shm/office-slides-view-modes-20261113/browser-03/downloaded.pptx \
PPTX_VIEW_DIRECTORY=/dev/shm/office-slides-view-modes-20261113/final-frozen-minimal-02 \
PPTX_VIEW_PORT=4511 \
node smoke/pptx-view-modes-smoke.mjs
```

续验范围仅为实际冻结入口、两张真实画布缩略图、Normal/Slide Sorter互切、草稿不写入与零保存；不重复源码层的拖排/备注/HTTP保存验收。浏览器关闭CDP缓存并阻止service worker。所有实际加载的冻结静态资源（含JS/CSS/字体等）逐项读取响应体并与最终资源文件SHA256核对；核验实际入口及可用的排序视图chunk已加载，同时确认manifest和两个引擎文件未变化。结果写入该目录的 `summary.json` 与 `frozen-minimal.png`。

预检：`node --check frontend/smoke/pptx-view-modes-smoke.mjs` 退出0；缺少真实重新打开文件时在创建目录/启动HTTP服务前立即失败。最终结果如下，源码完整链、懒绘制源码只读层和冻结minimal层保持独立验收边界。


- 最终通过目录：`final-frozen-minimal-02/`；机器汇总 `final-frozen-identity.json`。
- manifest SHA256：`845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c`，前后原字节保持。
- 实际HTTP返回的入口HTML SHA256：`43cc1ad00965a130ea569a88b05f8b3a35018a82678fe71cf35c77e1d74c9dec`，与冻结 `native.html` 原字节匹配。实际加载HTML引用的 `lazy-preload-helper-BPPmGX_j.js`、`lazy-unified-main-9f3XscT0.js` 和排序视图 `lazy-slides-view-modes-C2AER5B7.js`。
- 145个实际加载冻结静态响应（132 JS + 13 CSS）全部逐项匹配磁盘文件SHA256；完整逐资源身份在 `final-frozen-minimal-02/summary.json` 的 `assets`。
- 引擎前后身份保持：edit `b8123eb5de7c567438fee406cc6360794a01935aee07923b0f4076bb0dea03b9`，render `01f1e3db4efa04b4da730c2ac750b1db1a2e0badfb3eab934c6fed547ad05218`。
- 实际输入为前述已保存下载文件 `70dddfb33af981559c9d512fb5bcdeb618b03f3e3009af485852cdd76fff58a5`；重新真实授权导入，来源顺序为原页2、原页1。Normal/Slide Sorter入口和互斥状态、两张208×156真实画布缩略图已核，已目视 `frozen-minimal.png`；每张179个深色像素只证明内容绘制，不扩张成全排版验收。
- `http-evidence.json` 中保存请求0，完成修订0；浏览器、console和HTTP错误均为0。没有重复HTTP保存、重排/备注完整链或完整版式验收。
- 首轮 `final-frozen-minimal/failure.json` 保留：实际缩略图与双模式已完成且无保存，但harness错误假设manifest必有 `native.html` 项而失败。实读最终构建后确认HTML直接引用模块脚本；仅修复harness入口定位，按实际HTML引用校验后完成上述minimal续验。首轮保存请求同样为0。
- 本续验只修改专项文档及smoke；7个冻结产品源码SHA均与 `product-source-snapshot.json` 一致。未修改最终static、共享构建、产品源代码或业务验收状态。
