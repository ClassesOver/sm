# PR #207 / #208 后续：表格文字与标定测量

基线：`code` 合并提交 `7defea088513460bcbd8dcdcf78ae41d9f55872b`。固定 GenOffice 源为
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。本次仅关闭下面两个有界缺口。

## 原始来源与方法

- PPTX：直接获取固定源 `packages/pptx-engine/src/index.ts`，Git blob
  `055a3e7e49d6dee09d52410e04098e5b95746b40`，与本地 `git hash-object` 一致。
  复用 `editTableCellText`，不是重建整个表格。行/列指的是 XML 中 `a:tr/a:tc`
  原始索引，列索引不是合并后的逻辑列坐标。既有 `applyEditParagraphs` 保留对应段落属性，
  单段混合格式替换取原文本主导 run 的格式；这不等于保留被替换文字的每个 run。
- PDF：直接获取 `apps/pdf/src/renderer/measure.ts`（blob
  `24e849a33ce6b5a152681d8d514e5f5b8fa36296`，SHA-256
  `4d2ccdb5cc2bb69703a6e0e7fe708a49e1101d001ab75c220913c0dd0670e6dd`），
  逐字复用 `parseCalibration/formatLength`。核对 `MeasureScaleDialog.tsx`（blob
  `ba0be43e5c8cfdd4b4c2131c8ccae28d300a9d07`）和固定 App 的首条线确认、取消、重标定回调。
  保存复用固定 `DrawingInput.kind='measure'` 和 `save-pdf.ts` 的 Line/AP/Helvetica 路径。
- 验证先从真实 python-pptx 构造的 OOXML 和 pdf-lib 构造的 CropBox/旋转页开始，
  通过实际 Python 服务/打包引擎输出文件，再用独立 python-pptx/lxml 与 pypdf 检查。
  不能只凭编辑器自己回读或截图证明正确。

## PPTX 有界行为

原生对象下拉列表包括已有表格。检查器列出可编辑单元格（覆盖的合并槽位不出现），
支持多段文字、即时 render-tree、待保存记录撤销、NativeDraft 历史和恢复。
保存请求 `tableCells[{slideIndex,elementId,row,col,text}]` 绑定来源修订/SHA；拒绝重复目标、
不存在/非表格/被合并覆盖的槽位、越界/非整数、未知字段、控制字符及超额输入。
每次最多 500 个单元格，每格最多 20000 字符。来源页删除不得同批引用它。

复制先于源表格修改，因此复制的是保存前页面。表格文字修改先于 `addTable`，避免该操作
重新解析引起对象身份变化。网格、合并信息、`bodyPr/lstStyle/tcPr` 与未编辑单元格保留；
独立 ZIP/XML 比较检查未编辑文件内容逐字不变（ZIP 目录条目/压缩容器不要求相同）。

尚未接通表格行列增删、合并/拆分、尺寸、边框/填充、单格富文本选区和表格上下文 Ribbon。
本次不宣称完整 Table Design/Layout 对齐。传统非原生保存入口不展示此编辑面板。

## PDF 有界行为

Annotate ▸ 测量：画参考线后输入实际长度与单位，确认才产生第一条测量；取消/Esc 不产生修改。
固定公式是 `实际值 = PDF坐标线长 / pointsPerUnit`，保留两位小数。
同一视图后续线段复用比例；再次点击已激活的测量按钮，下一条线重新标定。
旧标签保持不变；取消重新标定保留原有效比例。比例只在会话内，新视图/刷新必须重新标定；草稿中已经提交的标签不重算。

沿用 PDF.js 逆变换，夹取和舍入端点后才计算标签，绑定不可变来源页，支持偏移 CropBox
及 0/90/180/270° 旋转。弹窗提交检查文档、完整草稿快照、只读/保存/预览/打印/销毁状态。
空白页未保存前仍不接受绘图。

固定引擎 Helvetica 直接写标签，本适配层将单位限定为 1–12 个可打印 ASCII（如 m、cm、mm、ft、in），
完整标签 1–64 个字符；额外拒绝非有限/下溢比例、过短线段和不可表示长度。此项比源的任意单位严格。
保存 Line `/L`、`/Contents`、`/AP` 和可解析 `/F1` 字体；这是带静态标签的标定测量，
不宣称写入标准 PDF `/Measure` 比例字典。源页 UserUnit/缩放不作为真实长度单位，用户参考线定义比例。

已有测量/绘图选择移动删除、线宽控件、面积/周长、跨不同图纸比例自动识别仍未开放。
安全涂黑、完整表单设计、证书签名和其他既有缺口保持开放。

## 可复验检查

- Python：`test_slides_engine_bridge.py` 与 `test_native_office.py` 中 `-k table_cell`，
  含真实保存/inspect、多格合并/格式/未改 ZIP 文件比对、复制+新增表格及非法输入。
- 前端：`pdf-drawings.test.ts` 的标定/端点夹取/非法比例；`slides-native.test.ts`
  的单元格恢复/精确身份与非法合并槽位草稿保留；关联既有历史/命令测试。
- 引擎：`node --import tsx --test bridge/drawings.test.ts`，检查 Line 端点、标签与字体资源及负例。
- Chromium：`smoke/pdf-measure-smoke.mjs`、`smoke/pptx-table-cell-smoke.mjs`，
  使用生产静态包和实际 Python 引擎保存下载，以 pypdf/python-pptx 独立回读。
  浏览器 fixture 替代 context/修订登记/下载授权路由，**不是生产鉴权或 SQL 验收**。
- Standard/Slides 构建、Standard budget、源身份与变更哈希检查；不重复完整仓库测试。

运行记录和导出文件见 `/workspace/scratch/pr207-208-next/`。功能开关保持关闭，未合并或部署。
完整桌面、真实生产授权/SQL 和干净完整应用镜像验收仍属整体计划未完成项。

## 本轮结果

- 前端受影响测试 85 项通过；已有 Ribbon 的 23 项检查通过。表格检查器最终显示调整后，两个新增单元格用例另行复验。
- 四个新增 Python 用例通过，另两项已有表格组合/更改形状回归通过；PDF drawing 引擎六项通过。
- 两个生产静态 Chromium 场景通过：PDF 五条测量跨四种旋转、取消/重标定/刷新后重标定/只读及下载；PPTX 多格/合并起始格、实际 render-tree、撤销/重做/恢复、保存/下载/重开。
- `--network=none` 的 Node 22 容器分别执行打包后的 PDF/PPTX inspect 和 patch，输出用宿主 pypdf/python-pptx 独立核验。挂载运行时只读，此证据不是完整应用镜像验收。
- Standard 和 Slides 构建通过，Standard budget 通过。Ruff 应用文件零诊断，测试文件保留基线 40 项、无新增。独立 PDF strict tsc 仍有六项既有 Electron resourcesPath/未打包 UI 类型诊断，不能描述为完整 PDF 引擎类型检查通过。
