# Word 只读标题导航专项

固定参考来源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用已 vendored 的 `collectHeadings`、`buildHeadingTree`、`visibleRows`、`headingAtPos`，适配原生只读导航，不复制完整 NavPane。

## 本次范围

- 当前正文标题树，包含空标题、重复标题，以及来源样式继承标题语义的普通段落和编号列表。
- 独立展开/折叠、选区定位、活动标题；子标题隐藏时父标题承接活动状态。
- 打开/关闭、实时正文更新、当前编辑器内折叠状态随事务映射。只读和保存中仍可导航。
- 仅选区事务：不写文档、撤销历史、草稿、源 DOCX 字节或下载产物。面板和画布并排；关闭与 dispose 解绑事件。
- 页面缩略图、导航内全文搜索、标题移动/删除/升级均未实现，界面说明此边界。

## 定向测试

2026-11-11：`npx vitest run src/docx-navigation.test.ts --maxWorkers=1 --minWorkers=1`，7 项通过。真实 Tiptap Editor 检查点击选区、文档/更新回调/撤销栈/草稿/存储不变、只读与保存中、重复/空标题、动态标题更新、关闭与 dispose。先运行新增测试确认缺少导航模块失败，再实现。

`node --check smoke/docx-navigation-smoke.mjs` 通过。独立真实 Python DOCX fixture 创建/inspect 通过：重复标题、空标题、继承样式标题均导入，编号继承标题确认为 `listItem`。

## 冻结构建浏览器验收

2026-11-11 已对 root 提供的 `final2-static` + `final-engine` 完成真实 Chromium 140.0.7339.16 验收，退出码 0。随后对大纲专项 CSS 修复后的 `final3-static` 完成同源浏览器复验通过；未重复单元测试。

运行示例：

```bash
DOCX_EXPECTED_MANIFEST_SHA256=<冻结hash> DOCX_TEST_PORT=4335 node smoke/docx-navigation-smoke.mjs
```

可通过 `DOCX_TEST_DIST`、`DOCX_TEST_ENGINE`、`DOCX_TEST_OUTPUT` 指定冻结目录与证据输出。沿用现有专项 smoke 的本地静态 fixture HTTP server 和替身 context/file/preview API 模式，真实 Chromium、实际 DOCX 解析；明确不代表生产鉴权验收。

脚本检查 editable + readonly、实际标题点击和折叠、键盘、并排几何、不新增 save/export 请求、文档 DOM 与 localStorage 不变，编辑标题后导航不增加已有草稿变更；收集 manifest、bridge、浏览器已加载 JS chunk SHA-256、源文件身份、请求记录和截图。

## 2026-11-11 final2 实测记录

- manifest SHA-256：`d16219950a133f029b252e955593dc52b6693013f0e146bbce73fcddf6e2c3e2`。
- DOCX bridge SHA-256：`ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6`。
- 实际加载 125 个 JS 文件，逐个核对浏览器响应字节与冻结静态目录 SHA-256；运行前后 manifest、bridge 未改变。
- editable 与 readonly 两个页面均通过空标题、重复标题、继承正文/编号标题、点击选区、独立折叠、Home/ArrowRight、关闭重开、活动项检查。
- 导航前后文档 DOM 和 localStorage 均不变；6 条 API 请求只有 context/file/preview，没有 save/export 请求，`errors=[]`。已对 source.docx 实际字节身份复核。
- 修改继承正文标题后导航实时更新，再次点击其他标题不增加已有草稿变化。
- 1440px 视口实测左导航右边界与画布左边界均为 240px，画布右边界 1440px；截图目视无重叠、无超屏。
- 证据：`/tmp/sr-word-navigation-20261111/navigation-browser/evidence.json`。成功截图：同目录 `editable.png`、`readonly.png`。
- 首次探针错误地假设导航按钮保留焦点时 `window.getSelection().anchorNode` 必有值，因其为 null 退出；改为读取 Tiptap DOM 附带的真实 Editor 选区后通过，无生产代码修改。首轮截图保留为 `first-attempt-selection-probe.png`，不属于最终成功截图，也不代表生产功能失败。
- 此验收为本地 fixture HTTP/API，未验证生产鉴权；保存中导航由真实 Editor 单测覆盖，浏览器未模拟在途保存请求。

## 最终 final3 同源验收

2026-11-11，root 统一构建后仅重跑本专项浏览器 smoke，退出码 0；没有重跑单元测试或自行 build。

- 静态目录：`/tmp/sr-word-navigation-20261111/final3-static`；引擎：`/tmp/sr-word-navigation-20261111/final-engine`。
- 最终 manifest：`6133a8fcdea51af52e3ae39ae5079dae5875acb4b161fda884e05e793cb86cc8`。
- bridge：`ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6`，与前一轮相同。
- Chromium：`140.0.7339.16`，125 个实际 JS 响应逐个 SHA-256 对齐，`errors=[]`。
- editable + readonly、空/重复/继承/编号标题、点击/折叠/键盘/活动项/开关均通过；标题正文实时更新后继续导航不增加已有草稿变化。
- 导航阶段文档 DOM 和 localStorage 均不变，6 条 API 请求仅含 context/file/preview，save/export 为 0；source.docx SHA-256 在运行前后保持 `db3189c29a97b77766133248ec5476f6ad9d3c66b7071facec185287c6a7fa02`。
- 并排几何仍为 panelRight=editorLeft=240px、画布right=viewport=1440px；成功截图目视检查无重叠。
- 最终证据：`/tmp/sr-word-navigation-20261111/navigation-final3/evidence.json`。
- 最终成功截图：同目录 `editable.png`、`readonly.png`；控制台记录：`/tmp/sr-word-navigation-20261111/navigation-final3-run.log`。
- final2 历史证据与首轮探针截图仍保留在原 navigation-browser 目录。生产鉴权、在途保存浏览器行为、页面缩略图及导航内搜索/标题编辑均不在本轮 browser 验收声明内。
