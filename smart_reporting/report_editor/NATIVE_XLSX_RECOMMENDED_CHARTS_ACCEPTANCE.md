# XLSX 固定源推荐图表入口

日期：2026-11-13。固定源：`/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 源映射与实现范围

- `apps/sheets/src/renderer/RecommendedChartsDialog.tsx`：九类型真实选区 SVG mini preview、七种推荐理由、排名卡片、点击插入和关闭。预览函数直接移植到局部 `workbook-recommended-charts-dialog.tsx`，模态管理复用现有 `createModal`。
- `visual-actions.ts:757`：选区→`recommendCharts`；本地引擎已有同源 `chart-recommend.ts`，不另写算法。推荐最多五项，按真实数据形状排序。
- `ribbon-actions.ts:801` 与 `App.tsx:4539/6201`：入口打开推荐结果，onPick 走统一插图路径。本地仅把既有 unsupported 入口改为真实命令，并在 main 内接选区与已有 `chartAdditionFromGrid`/operations/NativeDraft 链。
- `visual-actions.ts:217`：数值年份列在非散点图中作为类别。局部 `workbook-chart-add.ts` 补同源 `hasNumericYearAxis` 分支，避免预览为年份趋势而插入时把年份再画成一个系列。

打开和取消不产生 operation；点击推荐才新增图表。推荐源绑定实际 workbook/sheet core、来源文件、sheet 名与选区值，插入前及异步预检后重新核对。保护、工作簿替换或选区数据变化会拒绝旧推荐，不丢弃人工草稿。

推荐图表与已有图表修改共用原有预检、回放、NativeDraft 历史及保存链，没有新增 writer、AI 工具、Plotly、服务端路由或发布逻辑。未修改共享 static/dist、Vite 配置、SOURCE/hash 或总审计。

隔离回读探针发现本地既有 chart-add 尚使用旧 OPC 相对拼接，合法 openpyxl 绝对 drawing Target 被解析为错误路径；固定 f8 源 `xlsx-drawing-add.ts:984` 已支持绝对/相对目标，属于本地移植缺口。获准在 `ensureSheetDrawing` 复用已有 `relationships` 解析 mode、`resolveTablePartPath` 解析合法相对/绝对并拒绝 URI/越根；删除因此孤立的旧 `matchRelationship`，不重写 OOXML，也不改其他调用仍用的旧 resolver。HTTP 使用原始 openpyxl 绝对 Target 夹具验证，未以关系归一绕过缺陷。

## 定向验证

证据根：`/dev/shm/office-recommended-charts-20261113`，未重复完整 suite。

| 证据 | 结果 |
| --- | --- |
| `host-red.log` | 2 failed：真实推荐入口未接线；数值年份误当系列 |
| `initial-green.log` | 8 passed / 77 skipped：入口、年份、排名/预览、取消与目标、九种源 SVG 分支 |
| `focused-green.log` | 17 passed / 125 skipped（四文件共142例），包含旧 palette/几何回归及新增过期 data/protection/worksheet 拒绝、空数据与 ribbon 门禁 |
| `algorithm-green.log` | 既有同源推荐算法6 passed / 9 skipped，覆盖时间、占比、相关性、长标签、量级、多点、边界、去重和最多五项 |
| `drawing-target-red.log` / `drawing-target-green.log` | 独立7例关系边界测试 RED 4 failed / 3 passed；修复后新增7+既有chart-add6共13 passed，覆盖合法相对/绝对、External指向现有part、URI/网络路径/越根及原图、锚点、其他entry原字节保全 |
| `engine-typecheck.log` | package 与 bridge 类型检查 exit 0 |
| `typecheck.log` | 中间全局 tsc 因并行开发时尚未实现的 `pdf-bates` 模块与其测试隐式类型失败；不作为最终通过证据。root 最终统一冻结构建通过，使用下述 `845d9932…` manifest |

测试次数不可累计当成新增用例数。初轮 GREEN 与最终定向集合有重叠。

`verify-probe.log`/`verify-probe-diagnostic.log` 保留绝对关系失败；`verify-probe2` 是临时相对夹具对独立回读脚本的探针，不能算作缺陷验收。该归一代码已撤回，最终浏览器夹具为 openpyxl 原始绝对 Target。

## 真实 HTTP smoke

脚本：`frontend/smoke/workbook-recommended-charts-smoke.mjs`，独立夹具及回读：`frontend/smoke/workbook-recommended-charts-verify.py`。复用现有受控修订宿主 `workbook-ai-charts-server.py --source`。

最终结果：首次真实 HTTP 完整链执行即 GREEN，`browser.log` exit 0；未重跑完整链。证据为 `browser/evidence.json`，Chromium `140.0.7339.16`，Canvas 字体 preflight 通过、CDP 禁用缓存。

实际覆盖：

1. openpyxl 原始 XLSX 夹具包含 A1:B4 的 Year/Amount、2023/10、2024/20、2025/30 与一个原图；worksheet relationship 保持 `Target="/xl/drawings/drawing1.xml"`，未改成相对关系。
2. 真 UI 在 D20 输入 `Manual recommendation` 并加粗，再通过名称框选择 A1:B4、打开 Insert 推荐图表。排名依次为折线、柱形、饼图、圆环、条形；前两项理由为“时间序列适合用趋势展示”。折线预览实际 path 为 `M8.0,66.7 L90.0,37.3 L172.0,8.0`。
3. 关闭和 Escape 不产生图表 operation。点击折线卡片后，仅新增 Amount 一个系列，年份为类别、数值为 `[10,20,30]`；File Undo/Redo、reload 恢复均保留人工草稿和原图。
4. 保存 revision 4→5，`revisionRegistered=true`，授权下载与重开 `/api/file` 的 SHA 均匹配签发产物；`savedRevisions=1`、`plannerCalls=0`。
5. 独立 openpyxl/lxml/ZIP 回读通过：共两图，新图为 LineChart、单系列；类别为 2023/2024/2025，值为 10/20/30；引用为 `'Sheet'!$A$2:$A$4` 与 `'Sheet'!$B$2:$B$4`。D20 值及 bold、原图 `chart1.xml` 与原 anchor 保全；七个源 part 原字节一致，仅新增 `chart2.xml`。
6. 171 项 HTTP JS/CSS 与冻结磁盘资产逐 SHA 一致；manifest、workbook bridge、`native_office.py` 在运行前后身份不变。page、console、HTTP、asset error 均为空。

保存响应的业务验收仍为 `validation.ok=false`，具体原因 `native_source_review_pending`：“文件已保存；原生编辑内容尚未重新核验业务事实与完整版式。”实际 XLSX 已生成、登记、签发并下载成功，符合非阻断契约；本记录仅确认推荐入口及文件链路通过，不标记业务验收通过。

## 冻结身份与截图检查

最终构建由 root 统一生成于 `/dev/shm/office-four-format-source-library-20261113`；本专项未自行重建或改共享 static/dist。

| 身份 | SHA-256 |
| --- | --- |
| 源 XLSX | `0a4de7a67d9f85d7df032b8880e4278a9d97a4c87612228352015f0125dd575f` |
| manifest | `845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c` |
| workbook bridge | `178ef82fd73c8138d3a6c5aaabfda783760e5c3da0faca4cc7fd68ea0b747a11` |
| `native_office.py` | `79eb0bbe143a4e26db7648b46964f6e7f803ab81a96bd3833bc51e20edea001a` |
| 下载 XLSX | `7d79ccfa23326729cf464512170b06698abded49d2edf3e26f44301bf766cab8` |

已人工检查三张截图：

- `browser/recommendations-desktop.png`：五张卡片三列布局，排名、图形和中文理由可读。
- `browser/recommendations-mobile.png`：390px 视口两列、可纵向滚动，关闭按钮可见；第五张卡片位于滚动区域。实测 left=20、right=378.796875、scrollWidth=clientWidth=357，无横向溢出。
- `browser/recommended-reopened.png`：新 Amount 折线、原 Keep original 柱图以及 D20 加粗人工文本均可见。

产品与 engine 源码继续冻结；历史 RED 和相对夹具探针保留，未混作最终验收证据。
