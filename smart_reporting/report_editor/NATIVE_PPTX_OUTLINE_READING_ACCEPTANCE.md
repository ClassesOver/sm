# PPTX 大纲与阅读视图专项验收（2026-11-13）

本专项继续现有 Normal / Sorter 实现，未重新建立文稿、工作区或保存体系。当前源码接线、真实源 HTTP 验证及 root 统一 v2/v3/v4 物理构建的零保存冻结验证已完成，最终入口以 v4 为准。下面分别记录源开发服务器与冻结静态资源证据，不将二者混同；当前 live 工作区的后续外部新功能不纳入该结论。

## 固定源与功能边界

固定源 `/home/junge/pros/genoffice-source-full`，HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

| 功能 | 固定源真实行为 | 当前接入 |
| --- | --- | --- |
| Outline 提取 | `apps/slides/src/renderer/App.tsx:205–235` 递归 group，合并文本行与空白；以首行首 run 字号最大、同字号 y 最小的对象为标题；其余按 y 排列 | `vendor/genoffice-slides/outline-of.ts` 提取原函数，函数正文独立比对完全一致 |
| Outline 视图 | `App.tsx:3795–3820` 替换左侧 rail，显示标题、前五条正文、必要的省略号和无文字页回退；点击选页，保留普通编辑画布 | `slides-outline-reading.tsx/css` 接入既有 current/order/renderTree，复用已有选页、删除与 NativeDraft 历史 |
| Reading 视图 | `App.tsx:2125–2158,3713–3750` 静态 `SlideThumb` 适配窗口、点击/按键翻页、前后页边界、Esc 回普通；包含隐藏页 | 复用源 `SlideThumb` 与既有图片加载器，保留 current/order；焦点、输入法和原生按钮激活保护避免误翻或双翻 |
| Ribbon | `components/Ribbon.tsx` 的 `onViewMode`、实际 `IconOutlineView` / `IconReadMode` | 普通 / 大纲 / 浏览 / 阅读四个入口互斥，备注 IME 拒绝切换时回同步实际状态 |

Reading 没有源播放执行链；只验收静态逐页浏览，不宣称动画、转场、音视频或全屏播放。Outline 是文字大纲浏览与选页，正文编辑由现有画布/对象编辑器完成，不宣称独立大纲编辑器。Normal 侧栏仍沿用现有宿主控件，源完整缩略图 rail 不属于本专项。

## 当前源码验证

证据目录：`/dev/shm/office-slides-outline-reading-20261113`。

- 定向命令：`TMPDIR=/dev/shm ./node_modules/.bin/vitest run src/slides-outline-reading.test.tsx src/slides-native-ribbon.test.ts src/slides-view-modes.test.tsx`；三个文件、50 项通过，未重复全量测试。日志 `current-unit.log`。
- `outline-source-identity.json` 记录固定源 HEAD 与提取函数一致性；函数 SHA256 为 `0065bcf9719b17bf09155ced378ccbf0d529f4b5885a041373b8fa15ef0b9606`。
- `smoke/pptx-outline-reading-smoke.mjs` 复用现有真实 HTTP 导入、编辑、工作区上下文、CSRF、保存、发布与下载链，memory repository 仅用作夹具；不是生产数据库授权验收。
- `browser-01/summary.json`：110 个实际源 JS/TS 响应；page error、console error、HTTP error 均为空。三页分别含七条正文、隐藏页、空白页。验收大纲提取和前五条、省略号、空白回退，Reading Canvas/隐藏页/键盘/边界/按钮空格单次激活/焦点与 IME/Esc，以及 390px 宽度适配。
- 视图切换不写 operations，也不产生保存请求；现有对象编辑器修改标题后，真实预览刷新大纲，Undo/Redo、Reading 往返与草稿刷新保持同一份 NativeDraft。
- 只执行一次现有文字保存，注册修订 2，签发后下载并重开；保存载荷无 `viewMode`。图片 `outline-source.png`、`reading-source.png`、`outline-edited.png`、`outline-mobile.png`、`reading-mobile.png`、`reopened-reading.png` 已视觉检查。

## 产物独立回读与非阻断状态

下载 PPTX SHA256：`aea1806ab2b8086f361a92c02f294cd2e22d9ec0b0c7396214ed384fd0fc111a`，与保存回执一致。`independent-readback.json` 使用独立 `python-pptx` 与 ZIP 回读：

- 仍为三页，第一页标题变为 `大纲编辑后的标题 <&> 😀`。
- 隐藏第二页标志、所有其余文字与讲稿、空白第三页及其讲稿均保留。
- 只有 `ppt/slides/slide1.xml` 内容变化，其余 50 个实体部件逐字节保持；新增 ZIP 目录条目不承载内容。
- 回执明确 `validation.ok=false`，原因 `native_source_review_pending`（尚未重新核验业务事实与完整版式）；下载照常签发，没有把该状态误标为验收通过。

## 冻结交接

产品文件已接线并冻结：`slides-outline-reading.tsx/css`、`vendor/genoffice-slides/outline-of.ts`，以及 `slides-view-modes.tsx` 的共用缩略图导出、`slides-main.ts` / `slides-native-ribbon.ts` / locales 的局部入口。测试与 HTTP smoke 是本专项辅助文件；本轮未触 `slides-native-chart-edit.ts`、共享 `static/dist`、总审计或发布配置，未 commit/push/deploy。

`source-freeze-sha256.json` 记录源码专项冻结时身份；共享 main/ribbon 后续统一构建另有身份。smoke 的冻结只读分支仅检查大纲/Reading/移动宽度，不执行保存，核对实际 HTTP 入口 HTML/脚本及每个静态响应的文件 SHA256。

## 统一 v2 冻结静态资源实证

root 提供的统一构建根目录：`/dev/shm/office-four-format-numbering-print-metadata-20261113-v2/source`。静态目录为其中的 `smart_reporting/report_editor/static`，引擎目录为 `smart_reporting/reporting/slides_engine`；本专项没有重新构建或修改它们。

`final-frozen-minimal-01/summary.json` 与同级日志记录真实 HTTP 重导入源码轮下载文件（SHA256 仍为 `aea1806ab2b8086f361a92c02f294cd2e22d9ec0b0c7396214ed384fd0fc111a`），检查编辑后大纲、前五条正文、省略号、空白页、实际 Reading Canvas、隐藏页翻页、键盘返回、390px 宽度与 Esc 退出。实际保存请求 0、完成修订 0、草稿 operations 为空。page/console/HTTP error 均为空。

- manifest SHA256：`6e565b64b5d5dd5f549202d8552e4f03d994559b64d9bad62e2a9d10456163ef`。
- 实际 HTTP 入口 HTML SHA256：`f28f979529665646929b244c57ddc8aa2de02d81bd4c097a5645e52c74afc282`，与冻结文件一致。
- HTML 实际入口脚本：`assets/lazy-preload-helper-BPPmGX_j.js` 与 `assets/lazy-unified-main-Dh058O1T.js`，均确认实际加载。
- 147 个实际静态资源响应（133 JS、14 CSS）全部逐个计算 SHA256 并匹配冻结磁盘文件，没有用 manifest 列表替代实际网络加载。
- 统一引擎 edit SHA256：`b8123eb5de7c567438fee406cc6360794a01935aee07923b0f4076bb0dea03b9`；render SHA256：`01f1e3db4efa04b4da730c2ac750b1db1a2e0badfb3eab934c6fed547ad05218`。
- `outline-reopened.png`、`reading-reopened.png`、`reading-mobile.png` 已逐一目视检查。该层是只读冻结验证，未重复源轮的业务保存或签发，不宣称生产部署或全面 PPTX 对齐。

## v3 新入口零保存续验

最终续验绑定 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v3/source` 物理快照。root 将 v2 基线仅叠加 XLSX 隐藏表修复后重新构建；独立逐字节对照确认本专项七个 PPTX 产品文件与 v2 相同，记录于 `final-v3-pptx-source-identity.json`。当前 live 的母版等外部修改不进入快照，也不计入本专项能力。

证据 `final-frozen-minimal-02/summary.json`、日志 `final-frozen-minimal-02.log`、紧凑身份 `final-v3-frozen-identity.json`。仍重导入同一源码轮下载 PPTX（`aea1806ab2b8086f361a92c02f294cd2e22d9ec0b0c7396214ed384fd0fc111a`），检查大纲与 Reading、隐藏页、键盘和 390px 适配；保存请求 0、完成修订 0、草稿 operations 为空；page/console/HTTP error 为空。三张 v3 截图已逐一目视检查，未重复保存或签发流程。

- v3 manifest SHA256：`490aa9f5b482fe532ebd24d01b1479fe7b85f60a5dbaab6f7863486c79701444`。
- 实际 native HTML SHA256：`800a9f2f9aea713245535d23fc443b8207c746ec42de0886908785b5e4997fea`。
- 实际入口为 `assets/lazy-preload-helper-BPPmGX_j.js` 与 `assets/lazy-unified-main-AhKJWo_P.js`；147 个实际静态响应（133 JS、14 CSS）全部 SHA256 与 v3 冻结磁盘匹配。
- PPTX edit/render 引擎身份与 v2 相同。本结论只覆盖本专项 v3 物理快照浏览器验证；统一类型检查与四格式总验收由 root 独立记录，不能从本专项零保存结果推断。

## 最终 v4 入口与版本分层

最终物理基线为 `/dev/shm/office-four-format-numbering-print-metadata-20261113-v4/source`。本轮仅执行一次 `final-frozen-minimal-03` 入口续验，没有再次业务保存、签发或引入 live 母版等外部产品修改。

| 统一版本 | 本专项记录 | 结论边界 |
| --- | --- | --- |
| v1 | 未建立本专项冻结浏览器记录 | 不作为本专项最终入口证据 |
| v2 | `final-frozen-minimal-01` | 第一份通过的统一静态入口，保留历史 |
| v3 | `final-frozen-minimal-02` | XLSX 隐藏表修复后新 manifest 的零保存续验，保留历史 |
| v4 | `final-frozen-minimal-03` | XLSX 边距恢复类别修复后最终入口；本专项以此为准 |

`final-v4-pptx-source-identity.json` 独立确认七个 PPTX 产品文件在 v2/v3/v4 逐字节相同。v4 manifest SHA256 为 `f9e161a924c55a6c9c0e5dc3bca80f5d9607b62e2c0552663bd39f830fd211be`；实际 HTTP native HTML SHA256 为 `b2693d7db9506a240ca768e33be181c81d579bbfce8bc18451bf6731fd77f9d6`，实际入口为 `assets/lazy-preload-helper-BPPmGX_j.js` 与 `assets/lazy-unified-main-uFYoB9jc.js`。

`final-frozen-minimal-03/summary.json` 与 `final-v4-frozen-identity.json` 记录：147 个实际静态响应（133 JS、14 CSS）全部 SHA256 与 v4 冻结文件匹配；同一下载 PPTX 重导入后，大纲、实际 Reading Canvas、隐藏页翻页、键盘、390px 宽度及 Esc 退出通过；operations 为空，保存请求 0，完成修订 0，page/console/HTTP error 均为空。桌面大纲、桌面阅读及移动阅读三张截图已逐一目视检查。PPTX edit/render 引擎身份保持 v2/v3 不变。

root 已独立报告 v4 统一 Vite、类型检查、体积预算与预算合同 exit 0；此处未重复执行这些全局检查。上述专项证据不扩大为完整 PPTX、母版功能或生产部署验收。
