# 原生 PPTX 填充与轮廓分组验收

2026-11-11。固定参考 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。
本专项补齐简单填充与轮廓的来源回填、侧栏交互和功能区一致性，不代表完整 FormatPane。

## 来源及范围

参考固定源 `apps/slides/src/renderer/components/FormatPane.tsx` 的填充、线条分组，
沿用已登记的来源 SHA256 `7af130c4cd8901b83c96ae7bd0f534c97ed8a083415518ccd624655516a342cd`，
中文 pane 文案 SHA256 为 `071ac21956cd1e4fb5a92c11a79ff95582f991af5a2b132ef82fb58f6f6692d8`。
颜色触发器复用 `SlidesFormatColorWell` 及固定源共享颜色图库；
`slides-shape-format-pane.tsx` 与 CSS 是宿主适配，不宣称完整源侧栏逐字复制或视觉完全一致。

- 单选安全来源 text/shape 时显示填充与轮廓，支持纯色、无填充、实线、无线条、
  六位颜色、0–100 磅之间的有效正数粗细及逐字段恢复来源。
- 轮廓改色保留真实线宽，改线宽保留真实颜色；功能区和侧栏使用相同来源摘要与候选。
  非预设线宽（验收来源为 2.25 磅）在功能区补入当前值，不猜测为 1 磅。
- 填充与轮廓分别判断来源能力：渐变等填充不可安全摘要时仅填充只读；
  虚线、箭头、透明/主题/缺省继承或未解析属性轮廓仅轮廓只读。
  明确简单 `noFill` 轮廓摘要为 null；缺失或复杂轮廓不冒充无线条。
- bridge 的 `inspectBrushSource` 收紧简单轮廓摘要，避免颜色/线宽写回重建整条复杂线。
  不扩展 wire、Python 发布签发链路或 Plotly。
- 200ms 合并同次输入，复用主入口单笔历史及草稿；撤销、重做、刷新和保存前 flush
  保留其他修改。输入错误可修正重试，改回来源不创建空历史。
- 切对象、外部回填、锁定和销毁令旧控件失效；锁定恢复后仍保留来源能力限制。
  复用颜色图库原生自定义颜色输入，同目标更新不拆卸输入节点。
- 格式刷应用时将原子 stroke 一起合并，避免对象展开合并导致颜色或线宽丢失。

## 已有定向证据

证据目录 `/tmp/pptx-shape-pane-20261111/`。沿用本轮已产生的日志，不重复完整测试：

- `component-red.log` / `component-green.log`：组件最初 5 项；
  `noop-red.log` / `noop-green.log`：无变化与防抖恢复来源；
  `ribbon-lock-red.log` / `ribbon-lock-green.log`：任意来源线宽和锁定后能力限制。
- `integration-red.log` / `integration-green.log`：主入口共享来源、复杂轮廓保护、
  历史、刷新和保存前 flush。
- `brush-red.log` / `brush-green.log`、`no-line-red.log` / `no-line-green.log`：
  bridge 来源轮廓与明确无线条摘要；`related-green.log` 覆盖共享颜色图库、
  陈旧控件保护及格式刷 stroke 原子合并。
- `tsc-focused-final.log` 为本专项定向类型检查；不宣称全局 TypeScript 诊断已清零。
- `build.log` 独立 Vite 构建完成，44.11 秒；输出临时目录，未覆盖共享 static。
  临时配置只排除会复制共享 PDF 资源的插件。既有构建警告保留在日志中。
- `budget.log` 检查 376 个 JS chunk，failures=[]，未调整预算：
  主入口 255410 字节（250KiB 预算剩 590 字节），形状分组独立 chunk 6768 字节。

本轮独立引擎 runtime 的 edit/render SHA256：

- edit：`0814aee61947db84d602e70eb2443ec6a94c085887aa8c66d1fc3e8a1a557b54`
- render：`4fd9061aca988f83794ee246227546f8fd46af9fe93a47475be0d9ebb3707592`

## 真实浏览器及下载独立核验

既有 `smoke/pptx-parallel-edit-smoke.mjs` 增加 `PPTX_SMOKE_SHAPE_FORMAT=1` 专项分支，
复用真实 Python/Node inspect、patch、render；鉴权/CSRF 是明确 route fixture。
`browser.log` 最终 ok=true，`browser/evidence.json` 记录 121 份实际加载 JS 的身份，
pageErrors、consoleErrors、routeErrors、failedResponses 全为空。
manifest SHA256 为 `e438210316810f0461c6e59b702ad8ba82a82a73a1c14e5af802f7c5b1fb8d13`。

已实际检查来源 2.25 磅回填、无变化失焦、原生颜色输入节点持续挂载、功能区改色保留线宽、
撤销重做、恢复来源、非法宽度修正、宽窄屏颜色弹层边界、复杂属性分别只读、
显式无填充/无线条、草稿刷新、未失焦输入 4 磅直接保存、下载签发身份和修订 2 重开回填。
`shape-format-wide.png`、`shape-format-narrow.png`、`revision-2.png` 已目视。

独立 ZIP/XML 核验脚本 `verify-download.py` 退出 0，结果为 `browser/independent-final.json`：

- 来源 SHA256：`fd1c8cb3a47ad36b52c1b8e0a19653ff96d3519be52ff2c866187a74265fd8d8`。
- 下载 47508 字节，SHA256：`0b9d4c72b47736409fe89b43e7d2f476e5387c2e0750766afd45bcb4e55ca81d`。
- 43 个未编辑文件部件按字节相同，仅 `ppt/slides/slide1.xml` 改变；
  主题、母版、版式、媒体、图表、嵌入工作簿和第二页均保留。
- `Format safe` 最终填充 `123ABC`、轮廓 `112233`、宽度 50800 EMU（4 磅）；
  `Format complex line` 仅填充变为 `445566`，带 algn、虚线、箭头的整条轮廓逐字相同；
  `Format complex fill` 仅轮廓变为 `ABCDEF`，宽度仍为 28575 EMU，整个渐变填充逐字相同。
- 所有文字、geometry、非形状 XML 不变；逐个移除明确选择修改的 spPr 属性后，
  除下述既有身份元数据外，形状其余 XML 按字节相同。

严格比较初次发现既有 `patchedElementXml` / `ensureCreationId` 会为脏形状补稳定身份：
本次 `Format safe`、`Format complex fill`、`Format empty` 新增 creationId。
核验仅精确排除这三个新增节点，未笼统忽略 nvSpPr 或整段元数据，也未修改保存器。
因此不能宣称所有非样式 XML 原始字节都不变；上述例外已单独登记。

生产鉴权、数据库、部署和 PDF 转换不在本专项证据内；辅助 PDF 使用有效附件占位 fixture。
代码未提交、推送或部署。

## 仍开放

渐变、图片、透明填充及复杂轮廓的编辑仍未开放；现有保护不等于这些能力已对齐。
会话基准百分比缩放的后续验收见 `NATIVE_PPTX_SCALE_ACCEPTANCE.md`。
图片原始尺寸基准的后续验收见 `NATIVE_PPTX_ORIGINAL_SIZE_ACCEPTANCE.md`。
通用侧栏的效果、文本框、旋转、整体布局及多选格式编辑
仍需后续专项。现有 geometry 和图表分组的验收边界继续适用。
