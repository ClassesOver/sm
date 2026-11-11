# Word 网格线专项

固定源：GenOffice f8c17004fb730df11f0f743164ffd8b4281bb38c。

## 源语义与接线

源 App.tsx:973 的 showGrid 默认 false；7683 将 onShowGrid 直接绑定 setShowGrid；8190 仅追加 show-grid class。ribbon-tabs.tsx:1617 点击 onShowGrid(!showGrid)，可用条件为 hasDoc，不要求 editable。此开关独立于 Word 版式 docGrid 和持久化表格 tableGridlines。

既有 vendor scoped.css:12770 为 .docx-native .show-grid .doc-page 定义两个方向的 1px 渐变、24px × 24px background-size、content-box origin/clip，颜色使用 --docs-paper-grid。直接复用源样式，不新增或复制 CSS。

createDocxGridlines({editor, root, onVisibilityChange?}) 返回 toggle()/refresh()/dispose()/visible/reason()；root 使用 .docx-native 下的 .docx-navigation-layout。只读与保存锁可切换；进入/离开大纲保持独立开关；refresh 只同步 class；dispose 幂等恢复原 show-grid class。没有 PM dispatch、文档 attrs、源文件、NativeDraft、storage 写入或事件订阅。

## 专项验证

2026-11-11 TDD：4 项行为 RED 后，npx vitest run src/docx-gridlines.test.ts 最终 4/4 GREEN。使用真实 editorExtensions、Guard 与 NativeDraft，验证纯切换零 transaction/update，doc JSON/HTML/UndoRedo/draft/storage 不变；已有正文草稿及实际 UndoRedo 保留；只读与大纲切换；refresh、dispose、销毁后禁用。

冻结构建后执行：DOCX_EXPECTED_MANIFEST_SHA256=<冻结hash> node smoke/docx-gridlines-smoke.mjs。必填 expected，缺少/不匹配立即失败。支持 DOCX_TEST_DIST（冻结 static）、DOCX_TEST_ENGINE（冻结 doc_engine 根目录）、DOCX_TEST_OUTPUT（证据目录）、DOCX_TEST_PORT（默认4276），DOCX_GRIDLINES_CASE 可定向 editable/readonly/mixed。

探针只启动 preview，不构建。真实 DOCX 包含标题、正文、表格、均匀双栏和两节 2 栏→1 栏混排；三场景通过真实 data-action=gridlines-toggle 按钮与 aria-pressed 切换，校验源渐变、24px 网格、content-box 范围及主题颜色变量；进入大纲后返回页面仍保持开关，正文/分栏/inline 布局/NativeDraft/全部 storage/保存状态精确一致。可编辑场景另验证已有正文编辑草稿不被开关改写，真实 Ctrl+z、Ctrl+Shift+z 保持有效。保存和导出请求必须为零。每个实际加载 JS 与冻结磁盘 SHA-256 比较，manifest 与 engine dist/edit-docx.mjs 前后身份核对并记录。

## 边界

本开关不读写 Word 完整版式 docGrid，也不切换表格虚线网格。服务端文档保存/导出不接收此显示状态。固定源 show-grid CSS 本身没有 @media screen 限定，本轮不擅改源打印行为，也不宣称已保证浏览器打印隐藏；PDF/Word 导出是否排除显示网格应以独立导出链路实测为准。本地 fixture 与冻结构建验收不代表生产鉴权验收。

## 2026-11-11 冻结浏览器实测

三场景 editable/readonly/mixed 最终全部通过，实际按钮为 gridlines-toggle。冻结 static：/tmp/sr-word-view-tools-20261111/final-static；manifest SHA-256：8e5131fa4fb5fe7f784f3e4803f2a60307df5b876d2bd87b8d1a7e610a94ba92。冻结 engine：/tmp/sr-word-view-tools-20261111/final-engine，桥文件运行前后均为 ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6。128 个实际加载 JS（含解析 worker）逐个冻结磁盘 SHA-256 匹配，errors=[]，saveExportRequests=[]。未 build、未改生产或注入临时样式。

计算样式证明复用源两方向 rgba(43,124,211,0.13) 渐变；两个 background-size 均 24px 24px，origin/clip 均 content-box。三场景网格→大纲→页面保留开关，关闭后恢复原背景；正文、列坐标 CSS 声明、分栏、草稿、全部 storage、保存状态不变。editable 另证明已有正文草稿在切换后不变，实际 Ctrl+z/Ctrl+Shift+z 可撤销与重做。

最终 JSON：/tmp/sr-word-view-tools-20261111/gridlines-browser/final/result.json。同目录截图：editable-grid.png、editable-outline-grid.png、readonly-grid.png、readonly-outline-grid.png、mixed-grid.png、mixed-outline-grid.png。已目视 mixed-grid.png，源网格仅覆盖内容框，分栏正文正常。

首轮测试证据保留于 /tmp/sr-word-view-tools-20261111/gridlines-browser/failure.html、failure.png。该次混排断言唯一差异为大纲 decoration 清理后的分节符 style 属性由不存在变为空字符串，实际 CSS/正文/列坐标/草稿均未变化；因此仅修正 smoke 使用 CSSStyleDeclaration.cssText 比较样式声明，未改生产逻辑，随后同一冻结构建三场景通过。
