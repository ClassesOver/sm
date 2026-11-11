# 导航内纯字面搜索

固定参考来源：GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。使用现有 `compileFind/findInDoc/findInDocAsync/matchContext`，不新增匹配引擎，不修改 vendor 或已有查找替换。

## 支持范围

- 当前 ProseMirror 正文和表格文字；匹配跨文字格式 run 与非 BMP 字符，忽略大小写及全半角，遵循源长度保持的折叠规则。
- 搜索框纯字面：源 literal 模式仍识别 Word 的 ^ 代码，本框用源明确约定 ^^ 转义每个 ^，因此 ^p、^l、^ 和 .* 都按实际文字查找；不跨段落/硬换行边界。
- 查询时不移动选区；点击结果、上下个、Enter/Shift+Enter 才精确选中匹配范围并循环导航。
- 输入自动切换到结果列表，清空恢复标题树和折叠状态；只渲染前 500 条，上下个仍遍历全部匹配。
- 结果上下文通过 createTextNode/textContent 和 mark 构建；没有把文档/查询插入 innerHTML。仅结果列表 mark 强调，不添加全文高亮、不写共享 searchPluginKey，既有查找替换高亮可共存。
- 超过源 SCAN_THRESHOLD 的文档使用源异步分片扫描，新 query、关闭、销毁与新正文取消旧扫描；public navigation.refresh() 读取实际当前文档，支持外部回滚 updateState 后刷新。
- 只读/保存中仍可搜索和导航；不写文档、原生草稿、撤销历史或源字节。onSearchNavigate 可选回调仅在真实跳转前触发，root 将其接到页面视图，保证大纲隐藏的正文恢复可见。
- 不含页眉页脚、独立嵌套编辑器、受保护区域和非文字叶子；不做替换、正则/通配符开关、页面缩略图、标题编辑或跨段落搜索。

## 定向单测

2026-11-11：先新增真实 Editor 的 12 项搜索测试，全部在“导航必须提供搜索框”断言 RED；实现后新 12 + 原有导航 7，共 19/19 GREEN。

新增 onSearchNavigate 时先跑一条小回归 RED（实际只有 selection 事件，缺 callback/page），实现后仅跑新 3 项：回调时序/无写入、updateState 回滚后 public refresh + 旧异步保护、硬换行与 ^l 字面边界，3/3 GREEN，没有重复完整测试。

这些测试覆盖纯搜索 doc/draft/localStorage/undo 不变、readonly/saving、现有查找高亮不变、跨 run/非 BMP/表格、空/无匹配/清除、动态结果与精确位置、500 cap/全部跳转、新查询与 dispose 旧结果隔离、DOM 文本安全。

## 浏览器验收

2026-11-11 已使用 root 统一冻结构建完成真实 Chromium 验收，退出码 0。没有自行 build 或复跑全量测试。

`node --check smoke/docx-navigation-search-smoke.mjs` 已通过；真实 Python 创建/inspect fixture 已通过，包含多格式 run、非 BMP、全角、^ 文字、HTML样式文字、表格、503 次 cap 匹配。

本次 smoke 沿用本地 fixture 静态 HTTP server + context/file/preview API 替身，真实 Chromium/真实 DOCX 解析；不代表生产鉴权。实测覆盖 editable+readonly、原有查找替换高亮共存、outline→正文结果自动回页面、精确匹配、上/下个/Enter/清除、cap、动态修改后导航不追加草稿/历史、文档/存储不变、0 save/export、实际加载 JS/manifest/bridge/source SHA-256 与截图。失败刷新由真实 Editor 的 updateState 回滚单测证明，browser 无独立失败注入入口。

默认端口 4336。冻结时通过 DOCX_TEST_DIST、DOCX_TEST_ENGINE、DOCX_TEST_OUTPUT、DOCX_TEST_PORT、DOCX_EXPECTED_MANIFEST_SHA256 配置运行；最终实际证据与结论见下文。

## 2026-11-11 冻结构建浏览器结果

- Chromium：140.0.7339.16。统一静态目录：/tmp/sr-word-view-tools-20261111/final-static；engine：同任务目录 final-engine。
- manifest SHA-256：8e5131fa4fb5fe7f784f3e4803f2a60307df5b876d2bd87b8d1a7e610a94ba92；bridge SHA-256：ac7b4fdded02ec349e44e49967a57af9a10f7fd37060d51307d95eacdf7f14c6，运行前后均未改变。
- 128 个实际加载 JS 响应逐个与冻结磁盘文件 SHA-256 核对；errors=[]（pageerror 与 HTTP 失败记录）。
- editable + readonly 都能找到 5 个 cat 匹配，😀cat 跨格式 run 精确选区 UTF-16 跨度为 5；表格结果定位到真实 cell 深度 4。
- ^p、^、.* 和 HTML 样式文字均按字面查找，结果 mark 使用安全文字节点；没有生成 img 元素。不跨段落，无匹配时禁用上下按钮。
- 实际 503 个 cap 匹配只显示 500 条；“上一个”可从未选择状态跳到 503/503。输入 query 不移光标，点击/Enter 才精确选择；清空恢复标题树，关闭重开保留查询。
- 搜索前后文档 JSON、localStorage、undo/redo 可用状态不变；原有查找替换面板的两个“边界” search-hit 高亮保持，导航不新增全文高亮。
- 大纲内输入查询仍处于大纲，点击正文结果才通过 onSearchNavigate 自动回页面视图，aria-pressed 同步；只读下同样通过。
- 真实键盘把普通段落 cat 改成 dog 后，搜索从 5 处实时降到 4 处；后续搜索导航不增加该草稿或撤销历史。
- API 记录共 6 条，仅 context/file/preview；save/export=0。源文件实际字节运行前后身份未变。
- 左导航右边界=画布左边界=240px，画布右边界=视口1440px；editable.png 与 readonly.png 均已目视检查，无导航/画布重叠或横向超屏。
- 最终证据：/tmp/sr-word-view-tools-20261111/navigation-search-browser/evidence.json；成功截图：同目录 editable.png、readonly.png。本次首轮浏览器即通过，没有失败截图。
- 失败刷新、保存中导航、旧异步扫描与dispose由真实 Editor 定向单测覆盖，browser 未模拟在途保存或失败回滚；生产鉴权未验。

- 实际导航 chunk：/reports/v1/editor/assets/assets/lazy-docx-navigation-By1qfNJo.js；SHA-256：536a82c4cc5a6113fb07628c70e604cd7f52cdfc99e9b4a3d4c046105b2cbd92。
- 此轮源 DOCX SHA-256：510dbe420d3a9fee7ed5079e8188c59b94094498c3c3b8252a5b922c64a0f401。
