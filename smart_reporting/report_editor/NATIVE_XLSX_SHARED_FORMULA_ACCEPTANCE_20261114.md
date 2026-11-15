# XLSX 共享公式读取与安全保存专项验收

参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；本地基础 `1e4a0a34` 加工作区改动。日期 2026-11-14。对应账本 data F08（稳定记录 ID D08）。

## 本批交付

- 读取显式存储的 shared master/follower，展开相对引用并保留 `$` 锚点、样式和函数存储标记归一。支持自闭合及成对空 follower、主单元格后置和多个独立组；不按 `ref` 矩形凭空补单元格。
- 改写组内任一单元格的值／公式前，先把整组拆为普通公式。替换或清空 master 不再丢失其他 follower 的原始公式。拆组仅替换 `<f>`，保留其他单元格属性和缓存字节；纯样式和无关组继续保留 shared XML。
- 复用的 copy/fill 引用转换器保护字符串、显式／隐式／转义结构化列名、Unicode／反斜杠／越网格名称、外簿与三维工作表限定符，以及 OFFSET/INDEX/命名范围端点。真实越界的单元格偏移生成 `#REF!`。
- 保存差异逻辑不再把同一公式重新计算出的数值当作用户修改；真正的公式改写、删除及样式修改仍进入原保存链。
- 缺失或重复 master、无效 si 等组结构显式报错，避免静默导入为缓存常量。

## 证据

初始真实 ZIP 回归为 **15 失败／3 通过**。独立同模型代码审查先后复现结构化引用、名称、三维限定符及范围端点误转换，均补 RED 用例后修正；末轮审查无剩余发现。

最终定向测试：引擎 **115 通过**（9 文件，其中新共享公式测试 28 项）；前端 **126 通过**（12 文件）。覆盖读取／编辑／格式、已有 Paste Special、条件格式结构平移及未来函数标记。引擎和前端实际导入闭包的严格 TypeScript 检查通过。未重复完整测试套件。

真实 Univer 0.25.1 插件与公式引擎测试从实际 XLSX 导入 stale cache `999`，实际计算为 `4、6、8`；初始保存差异为空。master 改为 `42`，撤销／重做后只产生一条用户写入；保存重开与重新计算后得到 `42、6、8`，follower 保持 `=A2*2`、`=A3*2`。该测试运行于 jsdom 中的实际 Univer core，无网格／公式 mock。

另生成 master 值替换、公式替换、清空三份真实 XLSX，独立 openpyxl＋ZIP/XML 回读确认其他公式、缓存 `6、8` 和非目标包内容保留。原始输入、3 份输出、生成脚本及独立回读结果位于 `/tmp/xlsx-shared-20261114/`；`source-binding.json` 绑定本批代码／测试 SHA256。

日志：`/tmp/xlsx-shared-{red,review-red,range-red,name-range-red,final-engine,final-frontend,final-ts,frontend-ts}-20261114.log`；真实计算差异的失败／通过另见 `xlsx-shared-diff-{red,green}-20261114.log`。日志中的 Univer `getSnapshot` 弃用提示来自既有 readBack 链。

## 边界与未通过项

这是 eager 模型中显式 shared 单元格的专项关闭，不是完整 Excel 或全 XLSX 对齐。通用不支持函数缓存兜底（F07）、数组／动态 spill（F09）、最新公式缓存持久化（F11）、流式／索引加载（F12）、结构改动与所有宿主组合仍独立开放。没有运行桌面 Excel、完整应用浏览器下载、真实 provider 或生产保存链。

尝试加载 `workbook-main-calculation.test.ts` 中的共享依赖删除用例时，因现有 DOCX 依赖 `fast-xml-parser` 缺失而未能收集；此项没有计入 126 通过数。独立 `workbook-cell-formula-removal.test.ts` 的 13 项通过，不替代上述完整宿主用例。

改动未提交、推送、合并或部署。
