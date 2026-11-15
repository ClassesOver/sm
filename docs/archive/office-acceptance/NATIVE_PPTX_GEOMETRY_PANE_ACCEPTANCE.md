# 原生 PPTX 大小与位置分组验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项补齐厘米输入、0.1cm步进、锁定纵横比和位置参考点，不代表完整FormatPane。

## 固定源与适配范围

核对固定源 `apps/slides/src/renderer/components/FormatPane.tsx` 的`sizeCommit`、
`spinRow`和大小/位置分组，以及`renderer/i18n/panes/zh.ts`的中文文案。
两文件SHA256分别为：

- `7af130c4cd8901b83c96ae7bd0f534c97ed8a083415518ccd624655516a342cd`
- `071ac21956cd1e4fb5a92c11a79ff95582f991af5a2b132ef82fb58f6f6692d8`

与vendor根`SOURCE-SHA256.json`的来源记录一致，独立证据为`source-identity.json`。
`slides-geometry-pane.ts`及其CSS是宿主行为适配，不宣称源FormatPane逐字复制或整体视觉对齐。

- 原生模式用右侧厘米分组替代可见像素输入；legacy编辑器保留原输入。
- 尺寸与位置显示两位小数，但计算使用真实来源96dpi geometry，`pxPerCm=96/2.54`；
  不使用画布fit/viewScale，不因失焦或重复输入原显示值把未编辑维度舍入写回。
  EMU相同的候选是无变化，不新增历史。
- 宽度、高度各提供0.1cm步进。锁定纵横比后，修改其中一维按当前真实比例同步另一维；
  位置保留原左上角，与源`sizeCommit`一致。
- 水平、垂直参考点分别选择左上角或幻灯片中心；中心参考显示对象中心相对页面中心的偏移，
  写入时转换回来源左上角。负的中心偏移可以输入，但转换后的实际位置仍受现有协议限制。
  参考点与锁比例仅为会话UI状态，不新增wire字段，也不写入PPTX元数据。
- 单对象且来源`arrangeEditable`的text/shape/picture开放写入；其他来源有geometry时只读并给原因，
  没有geometry或多选时隐藏。组合待保存及修订锁定禁用；页面尺寸待保存时提示先保存，避免源坐标与缩放后坐标混用。
- 完全复用现有geometry协议：实际位置0..100000px，宽高采用源最小1px且不超过100000px。
  空值、不完整数字、非有限值和越界不提交；提示保留供修正和重试。
  输入改回原显示值时清除旧错误，不伪造一次写入。

## 历史、裁切与交互保护

主入口经现有`commitNativeChanges`提交一笔历史，保留既有文字及其他操作。
有待保存图片裁切时直接更新其geometry，保留srcRect及expectedSha256/expectedSize，
不重复加入通用图片geometry覆盖；此前通用框修改若已被裁切取代，同一候选一起清理。
保存前flush尚未失焦的字段，失败时保留输入；撤销、重做、草稿刷新及修订重开均回填实际值。

切目标、外部回填、锁定及销毁令旧控件代次失效。自己的同步提交回填保留输入和按钮节点，
避免失焦提交拆掉紧接着要点击的步进按钮；步进不先抢焦点。
Enter提交，Escape恢复当前实际值。620px宿主三列布局中，本分组独占一行，避免被压入180px列。

本轮没有修改Python/bridge、发布门禁、非阻断签发、下载契约或Plotly代码。

## 定向验证与失败记录

证据根目录：`/tmp/pptx-geometry-20261111/`。不运行或重复完整测试集。
6个组件用例、1个新增主入口集成、1个既有图表侧栏关联用例，共8个不同用例分批通过：

- `component-red.log`：模块尚不存在时失败；`component-green.log`初次3过1失败。
  失败是测试在比例调整后仍用原宽度计算中心参考；改为通过高度调整恢复原尺寸，
  同时覆盖锁比例的两个方向，`ratio-green.log`通过。
- `input-identity-red.log`：真实暴露提交回填重建输入/步进节点；保留自己的同步回填节点后，
  `input-identity-green.log`的节点身份、精度、非法值/重试、陈旧控件4项通过。
- `integration-red.log`：新侧栏不存在；初次`integration-green.log`使用了10000而非0.1的
  裁切比例，被已有媒体校验正确拒绝。修正fixture后`integration-final.log`通过，
  覆盖文字合并、比例、单笔撤销/重做、刷新、只读、保存前flush和裁切框合并。
- `related-final.log`：比例用例通过；并行真实浏览器运行时既有图表用例超过默认5秒，
  没有断言失败。单独复验采用CLI 15秒上限，实际4.60秒通过，见`chart-related-final.log`；
  未改用例或应用代码来绕过断言，未改变全局测试时限。
- `correction-red.log`：非法输入改回原显示值仍残留错误；清理无变化校验状态后，
  `correction-green.log`通过，零额外写入。该修复另纳入最终真实浏览器检查。
- `tsc-focused-final.log`：新组件、主入口及集成测试定向TypeScript检查退出0。
  smoke的Node语法、Python AST及限定文件diff检查通过。未重跑全局tsc，
  不能将此前记录的`docx-ruler.test.tsx`诊断视为本轮已修复。

浏览器初次`browser-before-layout.log`在620px检测到实际宽180px、内容192px的溢出；
只修组件自身grid-column与控件样式后重新构建。`browser-float-check.log`随后误把来源裁切框
高度95.99999999999997要求为严格96，改为检查未编辑原值完全保留及写入EMU精确一致，
没有修改应用去舍入来源。修复错误提示前的完整浏览器验收与独立回读已通过，
证据保留在`browser-before-correction/`，它不替代最终构建的验收。

## 最终独立构建

`build.log`退出0，42.69秒。临时Vite配置仅关闭会写共享static的PDF资源复制插件，
输出独立`static/`，没有覆盖共享前端或引擎dist。`budget.log`检查375个JS chunk，无失败，
未改预算；分组独立chunk：

- `lazy-slides-main-CxgE0Bhp.js`：255398字节，250KiB预算内，剩602字节。
- `lazy-native-pptx-geometry-B54emDbc.js`：4659字节。
- manifest SHA256：`3d0dcafd6f3bcc8e9e0531e0066a6a5a7d0c6c1ed76080b01387464188fd876a`。

引擎没有修改，实际Python调用沿用前一专项独立runtime，身份为：

- edit：`6d4c127b39ac6ae5a89c5fe9f3683a02ba830024d86ae53ba90db68137497f60`
- render：`05f1574d88f1ec43e4f3af778c7bb2f3557101831ef404a71d4859c3bb8db918`

路径为`/tmp/pptx-chart-pane-20261111/runtime/dist/`，没有重跑Python/bridge全套。

## 最终真实浏览器与下载回读

扩展既有`smoke/pptx-parallel-edit-smoke.mjs`的`PPTX_SMOKE_GEOMETRY=1`专项分支，
复用同一鉴权/CSRF route fixture和实际Python/Node inspect、patch、render。
最终`browser.log`退出0、`browser/evidence.json`为ok=true，120份实际加载JS响应逐一核对
静态磁盘SHA和大小；pageErrors、consoleErrors、routeErrors、failedResponses均为空，
manifest在运行前后不变。没有把之前构建的成功结果替代为这次结果。

已实际验证：

1. 厘米值失焦不写入；锁比例改宽高、0.1cm步进、中心参考的正/负偏移转换；
   单笔撤销/重做、越界不提交、修正回原显示值清理错误且无新历史。
2. 1440×1100与620×900宽窄布局；窄屏分组无水平溢出，尺寸和位置分别聚焦截图。
   `geometry-wide.png`、`geometry-narrow.png`、`geometry-narrow-position.png`已目视。
3. 实际鼠标拖动固定源裁切覆盖层左侧手柄，Enter提交；之后改厘米宽度及位置，
   srcRect和图片身份保留，只有裁切geometry改变，未另造通用图片覆盖。
4. 刷新恢复完整草稿；图片高度输入3.81cm后不失焦直接保存，实际save输入包含144px高度。
   读取签发下载地址，实际下载bytes与回执SHA及大小一致。
5. 下载后python-pptx/ZIP独立回读，修订2使用下载bytes实际打开，厘米尺寸及srcRect正确回填，
   无变化失焦不建立新草稿。`revision-2.png`已目视。

独立脚本`verify-download.py`退出0，见`independent-final.log`及
`browser/independent-final.json`：

- 来源SHA256：`37fe0ebecfa6ddff9004be4ab9efae7e4365d754bfe45dd8dfd25a4cc1ec6fe2`。
- 实际下载47087字节，SHA256：`073ebc4541a6a9265c44d519ce12cac369f92536e0405c922c530b996eebe8d0`。
- 文本框最终EMU `[x,y,cx,cy]=[2743200,2148840,3657600,731520]`。
- 图片最终EMU `[914400,1828800,2743200,1371600]`，即左2.54cm、上5.08cm、宽7.62cm、高3.81cm。
- 原图片blob身份和所有文字保留；39份未编辑包部件按字节相同，包括主题、母版、版式、
  图表、嵌入工作簿、媒体及第二页XML。裁切比例按PPTX十万分之一单位容差回读。

授权和CSRF为明确的API route fixture，不覆盖生产鉴权、数据库或部署。
辅助PDF为有效attachment placeholder，不声称验证PDF转换或原生PDF插件。
代码未提交、推送或部署。

## 仍开放的范围

会话基准百分比缩放的后续验收见 `NATIVE_PPTX_SCALE_ACCEPTANCE.md`。
图片原始尺寸基准的后续验收见 `NATIVE_PPTX_ORIGINAL_SIZE_ACCEPTANCE.md`。
本专项未补旋转，也没有扩展负实际位置、图表/组合/表格
的geometry安全边界或多选尺寸编辑。简单填充/线条的后续来源回填与侧栏验收见
`NATIVE_PPTX_SHAPE_FORMAT_PANE_ACCEPTANCE.md`；复杂填充/轮廓编辑、效果、文本框及整体交互布局
仍开放，不能把简单fill/stroke写入当作复杂轮廓来源可安全回填。
