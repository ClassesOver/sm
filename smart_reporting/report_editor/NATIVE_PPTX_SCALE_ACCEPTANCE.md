# 原生 PPTX 会话基准百分比缩放验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项在已有大小与位置分组内补齐宽度/高度百分比输入和 1% 步进。

## 来源及行为边界

核对固定源 `apps/slides/src/renderer/components/FormatPane.tsx` 的 `scaleBaseRef`、
`scaleBasis`、`commitScale`、`stepScale` 与 `sizeCommit`，以及中文 pane 的
“缩放高度”“缩放宽度”文案。源码 SHA256 为
`7af130c4cd8901b83c96ae7bd0f534c97ed8a083415518ccd624655516a342cd`，
中文文案 SHA256 为 `071ac21956cd1e4fb5a92c11a79ff95582f991af5a2b132ef82fb58f6f6692d8`；
独立身份记录见 `/tmp/pptx-scale-20261111/source-identity.json`。

- 当前对象选中时的宽高分别作为 100% 基准，同目标的尺寸提交、厘米编辑、
  撤销重做和外部回填不重置。换对象或结束选择后重建；刷新或修订重开也重新建立。
- 连续输入 150%、200% 分别为基准的 1.5 倍、2 倍，不逐次复乘。
  图片同样使用选中时当前可见框基准；相对原始图片尺寸未纳入本专项。
- 百分比显示按固定源四舍五入到整数，计算保留真实来源尺寸。
  显示值未变化时不回写；可选 `%` 后缀不改变该无变化语义。
  可以提交小数百分比；空值、不完整数值、非有限值和越界结果不提交。
- 1% 步进按当前四舍五入百分比加减，最低 1%；最终尺寸沿用原生协议
  1..100000 像素边界，不改变原始位置、尺寸基准或画布 viewScale。
- 锁定纵横比时复用已有单维尺寸换算，联动另一维；厘米显示随实际尺寸更新。
  恢复到原显示值清除错误，保存前 flush 允许提交未失焦百分比。
- 同步宿主回填保留输入和步进节点。切目标、锁定、只读和销毁后的旧控件不能写入。
  主入口仍复用 `commitNativeChanges` 和已有裁切 geometry 合并路径，保留 srcRect、
  图片身份、正文和单笔历史。不新增 wire、Python/bridge 或发布签发逻辑。

实现仅扩展 `slides-geometry-pane.ts`，复用既有 CSS 和数据提交入口；
未调整包预算，未重构其他侧栏。

## 定向验证与失败记录

证据目录 `/tmp/pptx-scale-20261111/`。不运行或重复完整测试集。

- `component-red.log`：4 个新用例在百分比控件尚不存在时按预期失败。
- `component-green.log`：4 个百分比用例及 6 个既有厘米用例，共 10 项通过。
  覆盖会话基准、厘米联动、双向比例锁、步进、节点身份、无变化、非法输入、
  提交失败重试、切选择、锁定、只读和销毁。
- `integration.log`：新增主入口集成用例通过，验证正文保留、单笔撤销重做、
  重选/刷新基准、裁切记录/身份合并，以及保存前 flush 的真实 save 请求输入。
- `tsc-focused.log` 初次发现新增测试对通用 operations 对象的索引类型诊断；
  改用既有匹配断言后，`tsc-focused-final.log` 通过。
- 独立只读复核发现百分比后缀的无变化缺陷：实际 175.5%、显示 176 时，
  输入 `176%` 原先会错误提交为精确 176%。`suffix-red.log` 已复现额外提交，
  归一化后比较原显示值，`suffix-green.log` 通过。
  修复后再次定向类型检查见 `tsc-suffix-final.log`。

## 独立构建与包预算

`build.log` 为初次构建，51.33 秒；后缀修复后的 `build-final.log` 为最终构建，
45.73 秒，退出 0。最终输出 `static-final/`，不覆盖共享 static 或引擎 dist。
临时 Vite 配置只移除会复制共享 PDF 资源的插件；既有构建警告保留在日志中。

初次 `budget.log` 记录并行工作区中 Word chunk 256106 字节、超出 250KiB 的情况；
本专项未修改 Word 代码或预算。最终独立构建的 `budget-final.log` 检查 376 个 JS chunk，
failures=[]，最终 Word chunk 变化属于工作区其他变更，不能归功于本专项修复。

- `lazy-slides-main-CDjb_RTh.js`：255410 字节，250KiB 预算内剩 590 字节。
- `lazy-native-pptx-geometry-BRK9k9P7.js`：5076 字节。

## 最终真实浏览器与独立下载核验

既有 `smoke/pptx-parallel-edit-smoke.mjs` 增加 `PPTX_SMOKE_SCALE=1` 专项分支。
初次 `browser.log` 完整通过，输出 `browser/`，但它使用后缀修复前构建，
不能替代最终构建证据。后缀回归加入后，`browser-final.log` 再次退出 0，
结果为 `browser-final/evidence.json`，ok=true、revision=2。

最终构建 manifest SHA256：
`8c79637a9733aeefbbd248d7754b9fcc9b0b898bf5144c2c81078eda83519451`。
121 份实际加载 JS 逐份检查大小和磁盘 SHA256，manifest 在运行前后不变；
pageErrors、consoleErrors、routeErrors、failedResponses 均为空。
`scale-wide.png`、`scale-narrow.png` 与 `revision-2.png` 已目视。
宽窄屏分组无水平溢出；未据此宣称整个宿主 Ribbon 已在窄屏完全适配。

已实际验证：连续百分比不复乘、比例锁定与厘米联动、1% 步进、撤销重做、
整数显示及带 `%` 后缀的无变化保护、非法输入修正、重选/刷新基准重建、
真实鼠标拖动裁切后合并百分比 geometry、保存前未失焦字段提交、签发下载身份，
以及使用下载 bytes 打开修订 2 的真实尺寸回填。

`verify-download.py` 与 `verify-xml.py` 均退出 0，结果分别保存于
`browser-final/independent-final.json` 和 `browser-final/xml-final.json`：

- 来源 SHA256：`54ef66035aa37029fbf6cd8156b5340602ec8e9e6f6636deda097572907b9cb5`。
- 实际下载 47076 字节，SHA256：
  `ae9c9a685a99e6d33dfa19aaede87d533548ba2f655728dfb2a07b6ce62f6c0b`。
- python-pptx 独立回读文本框最终 EMU `[914400,914400,4286250,1143000]`，
  即宽 450px、高 120px；图片 EMU `[914400,1828800,2743200,1371600]`，
  即左 2.54cm、上 5.08cm、宽 7.62cm、高 3.81cm。
- 原图片 blob SHA256 不变，srcRect 按 PPTX 十万分之一精度回读；所有文字保留。
  43 个未编辑文件部件逐字节相同，仅 `ppt/slides/slide1.xml` 变化。
- 移除明确修改的 xfrm 和图片 srcRect 后，编辑对象剩余 XML 仅有既有保存器
  为 `TextBox 1`、`Picture 2` 补入 creationId 的差别；精确排除这两个节点后逐字节相同。
  所有其他对象和第一页非对象 XML 也逐字节相同。

Python/Node 使用前一专项独立 runtime，未修改或重建引擎：

- edit：`0814aee61947db84d602e70eb2443ec6a94c085887aa8c66d1fc3e8a1a557b54`
- render：`4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`

只读代码复核提出的后缀缺陷已修复并复核关闭，无其他未处理的重要发现。
鉴权/CSRF 为明确 API route fixture；辅助 PDF 为有效附件占位，
不能据此宣称生产鉴权或 PDF 转换已完成验收。

## 尚未对齐

图片原始尺寸基准及对应开关的后续验收见 `NATIVE_PPTX_ORIGINAL_SIZE_ACCEPTANCE.md`。
旋转、复杂填充/轮廓编辑、效果、文本框设置、
完整 FormatPane 布局和多选格式编辑仍开放。本专项不能视为这些能力已经完成。
生产鉴权、数据库、部署和 PDF 转换不属于本专项范围。代码未提交、推送或部署。
