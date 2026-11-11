# PPTX 图片、原生图表和查找替换增量计划

2026-11-11。用户授权并行推进 GenOffice 对齐缺口。固定参考源码为
`/home/junge/pros/genoffice-source-full` 的 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

本批沿用当前在途工作区与现有原生编辑流程，不复制旧提交覆盖在途实现。
三个并行任务各自拥有独立 helper、测试和专项记录；共享 Python、桥接入口、
`slides-main.ts` 与 Ribbon 由 root 集成。暂不覆盖图片裁切、复杂图表设计、多选排列、
放映、母版或完整格式对齐。

1. 图片：接入 PNG/JPEG 文件选择、按来源尺寸居中插入，以及已存在图片替换。
   复用 `addPicture` 和 `replacePictureBytes`；替换带来源媒体 SHA/size，保持共享媒体隔离。
   验证：真实文件回读、无关部件保留、过期身份/非法图片拒绝、草稿和撤销重做。
2. 图表：对固定引擎确认可改的原生图表开放类别/系列数据和类型编辑。
   复用 `editChartElement`，其他图表明确提示只读原因。
   验证：实际图表缓存和嵌入工作簿、类型、来源身份、未涉及部件、草稿与历史。
3. 查找替换：字面、不重叠、可选区分大小写；定位或替换来源顶层可编辑文字对象。
   复用已有 `edits` 与一次 NativeDraft 事务，排除删除页/对象；不新建 OOXML writer。
   验证：查找不改草稿，替换全部原子、撤销恢复、保存与真实文件文字回读。
4. 集成：先保留各项 RED，再完成最小 GREEN；只运行新增和受影响的定向测试。
   root 统一桥 bundle、前端构建和现有预算检查，使用构建后的浏览器专项做下载/重开验证。
   所有证据区分 fixture 授权、实际 Python/Node 文件链路和未验证的生产部署。

既有发布与下载非阻断契约保持不变，本批不改签发链。测试不通过时不将专项记为完成。

## 2026-11-11 集成验证记录

- 图片、图表、查找替换均已接入同一 `editSlides` 草稿、保存、恢复和撤销历史。
- 前端集成 4 项通过；图片改尺寸集成 1 项通过。图表弹窗异常留窗、陈旧确认拒绝、
  全部替换单次撤销、删除图片撤回待保存替换均有定向覆盖。
- Python 媒体请求契约 14 项通过；真实图片/图表/文字同批修改并重排文件回读通过。
- 重置版式与图片/图表修改同批、修改图表后复制页面的真实文件专项 4 项通过。
  重置前后通过来源 SPID 保留操作目标 ID；图表先修改再复制。
- 图表来源共享 chart part 或嵌入工作簿明确只读；标签限制跨层统一为 100 Unicode 字符、
  禁止控制字符，每批最多 50 条。
- 本轮 `npm run build` 的 TypeScript 步骤被并行在途 PDF 测试阻断：
  `native-pdf-extract-api.test.ts` 与 `pdf-extract-dialog.test.ts` 的 mock 空元组推断报错。
  未修改这些无关文件；另外运行 Vite 构建并对最终产物进行浏览器验收，结果待下附。
- `npx vite build` 成功（52.10s），`check:budget` 与 `test:budget` 均通过，预算未调高。
  本轮冻结的 manifest SHA256：
  `423db10838c554cc80c57cdf4fac99a75c5702c0ea3b4448fa6ba70edd32f67f`。
- 浏览器综合脚本的沙箱首轮卡在 Python `json.load(stdin)`；最小 Node `spawnSync`
  向 Python 传入 JSON 的探针同样超时。已按沙箱错误流程在沙箱外重跑，初始真实文件
  生成恢复为约 10 秒；该失败不计为功能通过，完整浏览器结果另附。
- 并行 PDF 工作于 10:19 更新了共享静态目录。重新确认 PPTX 主模块仍为
  `lazy-slides-main-DHsWZG3i.js`，未覆盖其他任务产物，综合验收改用当前 manifest
  `6fbdb541ca7e617bff0f7a3cb6891ccb039699b6d63178a482cc11384e43c918`。
- 并行任务随后修正了上述 PDF 测试类型声明；当前 `npx tsc --noEmit` 已退出 0，
  当前产物预算检查亦退出 0。未重新运行完整测试集。
- 共享静态目录继续被其他任务更新，最终转为独立快照
  `/tmp/pptx-parallel-20261111/static-frozen`（587 个文件，另存全文件 SHA256 清单）。
  复制前后及快照 manifest 三者一致：
  `dd6c99ba844347207505abe796d8a2b176999b0af7d1b6852c73434a36b61fd5`。
  该快照 336 个 JS chunk 的现有预算检查通过，未修改阈值。

## 最终浏览器验收

独立快照综合 smoke 退出 0，`ok:true`。在 Chromium 中完成图片插入/替换、
图表数据 37.5 与 line 类型修改、查找/全部替换、一次撤销重做、刷新草稿、保存、
读取界面签发链接下载、新修订重开并从图表弹窗读回 37.5。

- `pageErrors`、`consoleErrors`、`routeErrors`、`failedResponses`、运行期浏览器事件均为空。
- 109 个实际 JS 响应逐一核对冻结目录；root 再核对全部 587 个文件 SHA256，均未改变。
- 实际下载 PPTX 47,521 bytes，SHA256：
  `7c2325329e44941cce7793b6c763d251cd6d4291f8cebe41887254880be392ed`。
- python-pptx/ZIP 独立回读文字、图片字节及框几何、图表类别/系列/类型；未修改的
  master/layout/theme 部件身份保持。root 已目视新修订截图。
- 证据：`/tmp/pptx-parallel-20261111/browser-final/evidence.json`，同目录保留来源和下载
  PPTX、保存前与新修订截图。PDF 预览为明确的 attachment placeholder fixture；
  本次不验证 PDF 转换、原生 PDF 插件或生产认证/部署。

本批三项完成。后续仍需图片裁切、多选排列、完整放映、母版及复杂图表编辑等专项，
不能据此标记 PPTX 与 GenOffice 全面对齐。
- 引擎测试入口校准时曾运行一次包级测试：120 个文件、1276 项通过，9 个文件失败
  （包括缺少 `tools/ooxml-validate` 及 comments 等非本批用例）；不据此声明全量测试通过。
