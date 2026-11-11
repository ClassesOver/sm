# Word 导航页面专项

固定源 GenOffice HEAD：f8c17004fb730df11f0f743164ffd8b4281bb38c。

复用既有同源分页测量产生的真实 cuts/geoms/blocks；页面组件是本地 continuous PM 适配，不声称直接复用了 NavPageThumbs。原组件依赖 live page-wrap 和 gap ledger，宿主没有该结构，且零高度 gap 的真实 cuts 不能用其页数算法。

本地组件从真实 cuts.length 读取页数，以 start/end 选择真实块 DOM。测量返回后的屏幕 DOM 坐标按实际 zoom 归一化，缩进以 PM 内容原点计算。点击使用对应 lead 块的 ProseMirror 位置，既不估页，也不沿用 paperY 跳转。

## 支持范围

同纸宽高、单栏且能精确整块切分的当前正文。明确显示 unsupported 原因：段内 line/表格 row/cell 跨页、混合尺寸、镜像页边距、分栏/竖排、复杂浮动、纵向居中/底部对齐、多节不同页边距。页面仅为正文缩略图，不承诺页眉页脚或像素级打印预览。

页面克隆清除 id/contenteditable/autofocus、事件属性及 script/iframe 等资源脚本，不添加 doc-page/ProseMirror 类。纸张 inert 且不响应指针交互；缩略图点击取消默认动作，mousedown 保持真实正文选区。只读可查看和定位。

请求、文档、缩放、可见性、tab 和 dispose 身份变化后拒绝旧分页结果。切入页面 tab 先调用宿主 prepare，保证从大纲恢复页面视图再测量；搜索和标题行为保留。

## 定向验证

先 RED 后 GREEN。2026-11-11：页面组件 17 项通过，新增真实 cuts 零 gap 两页、line/row/cell/混合尺寸/镜像/分栏拒绝、2倍缩放归一、段前保留、首块缩进与后续无缩进、跨 cut 拒绝、blank 页保留、只读定位、克隆安全与交互隔离、五类旧请求拒绝。既有标题/搜索及新 tab 集成此前共34项通过；后来仅重跑变动的 pages 文件，不重复完整测试。

## 冻结浏览器验收入口

由集成人员先统一构建，设置冻结 manifest 身份：

    DOCX_EXPECTED_MANIFEST_SHA256=<冻结hash> DOCX_TEST_DIST=<静态目录> DOCX_TEST_ENGINE=<引擎目录> DOCX_TEST_OUTPUT=/dev/shm/sr-word-ruler-pages-20261111/pages-browser DOCX_TEST_PORT=4347 node smoke/docx-navigation-pages-smoke.mjs

脚本真实 Python DOCX + Chromium + fixture HTTP/API，验证 editable/readonly、真实3页及独立内容、从大纲切回页面、点击选区/活动页、标题来回切换、150%缩放仍3页、关闭重开、inert焦点保护、JSON/localStorage不变、无save/export请求；收集 manifest/bridge/浏览器JS响应/source的SHA-256、请求与截图。不代表生产鉴权验收。

当前已通过 node --check；浏览器结果必须由冻结构建实测证据确认，不预填通过。
