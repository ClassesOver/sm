# PPTX 无损裁切与多选排列验收

2026-11-11。延续用户授权的 GenOffice 对齐并行工作。固定参考源码为
`/home/junge/pros/genoffice-source-full`，提交
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 本批范围

- 图片裁切复用固定引擎 `editPictureSrcRect` 与来源 CropOverlay；裁切框及
  srcRect 同次撤销/重做，保留媒体字节、关系和来源身份校验，支持草稿恢复。
  旋转/翻转、分组、复杂图片及媒体海报等不支持对象保留只读原因。
- 多选复用固定引擎 `alignRects/distributeRects`，支持左/中/右、上/中/下
  六向对齐与横/纵分布。Ctrl/Meta/Shift 切换选择，也可使用对象复选框。
  一批排列记一次历史，使用当前裁切和几何草稿，零变化不新增历史。
- 多选时禁用文字、表格单元格、图表数据与动画等单对象入口；陈旧回调不可
  写入草稿。连接线端点随对象移动；保存继续复用原生编辑桥。
- 不覆盖框选、组合/取消组合、层级调整、母版或完整放映；不改发布签发链。

## 已有定向验证

- 裁切 UI 9 项、裁切桥 3 项、媒体草稿 6 项通过。
- 排列 helper/canvas 18 项通过；多选主集成 2 项、独立选择复核 4 项通过。
- 裁切主集成 3 项通过，覆盖历史/恢复/身份、陈旧确认、几何优先及替换互斥。
- 真实 Python/OOXML 裁切排列 5 项通过，包含共享媒体、恢复裁切、版式/重排、
  旋转翻转保留和连接线跟随。Ribbon 受影响 26 项通过。
- 桥 bundle、最终主构建（TypeScript + Vite）、现有资源预算及预算契约退出 0；
  Ruff 与 `git diff --check` 通过。未重复完整测试集。
- 随后补齐子应用时，`build:slides` 的全目录类型检查遇到并行新增的
  `docx-bookmarks.test.ts` 缺少模块等错误；该次失败不能计为通过，未修改无关
  Word 文件。独立 Vite 幻灯片子构建退出 0；管理子构建与资源预算退出 0。
- 选择复核的早期 `selection-review-green.log` 包含一次失败，最终通过记录为
  `selection-review-final-green.log`：11:27:52 运行该文件的 4 项窄测试，
  全部通过。未改代码，未重复完整测试。

证据根目录：`/tmp/pptx-crop-arrange-20261111/`。
浏览器验收使用独立 static 快照；认证与辅助 PDF 明确为 fixture，不据此声明
生产认证、真实 PDF 转换或部署通过。

## 最终浏览器验收

- 主代理运行 `smoke/pptx-crop-arrange-smoke.mjs` 退出 0，`ok:true`。
  完成真实裁切手柄拖动、Enter 确认、撤销/重做、三对象对齐/分布、刷新恢复、
  保存、签发链接下载、新修订重开和重新进入裁切后 Esc 取消；取消不产生草稿。
- Python 原生 inspect/patch/render 与 python-pptx/ZIP 独立回读确认：裁切媒体
  字节不变，srcRect/框几何写入正确，对齐坐标与分布间距正确，文字保留；
  第二页及除目标 slide1.xml 外的全部来源 ZIP 部件身份保持。
- `pageErrors`、`consoleErrors`、`routeErrors`、`failedResponses`、验收期间
  `runtimeEvents` 均为空。root 独立核对 108 个浏览器实际 JS 响应与冻结文件一致，
  全部 800 个静态文件 SHA256 未改变，保存前和新修订截图已目视。
- 冻结 manifest SHA256：
  `c32a1ee0c4302928f9443f1c08d09baf62f3555ed15f39e7e056eae3467ae6ef`。
- 下载 PPTX 为 42,503 bytes，SHA256：
  `e9bea7b8f4af93d03ba8394449ef2800109973e8ccb084ed63023dfc72327fab`。
- 最终证据：`/tmp/pptx-crop-arrange-20261111/browser-root/evidence.json`；
  日志为父目录 `browser-root-final.log`，同目录保留来源/下载 PPTX 与截图。
  子代理首次运行继承旧 restricted sandbox，停在 fixture 创建后被中断
  （退出 130），其 `browser-final.log` 不计通过；最终运行使用相同冻结产物。

本批两项完成，未提交、推送或部署。完整 GenOffice 对齐仍有框选、组合/层级、
完整放映、母版和复杂图表格式等专项缺口；旋转/翻转等受限图片仍不开放裁切。

后续补充：来源对象的厘米尺寸、纵横比锁定和位置参考点见
[大小与位置专项](NATIVE_PPTX_GEOMETRY_PANE_ACCEPTANCE.md)。该分组在待保存裁切上
修改框位置与尺寸时保留srcRect及图片身份，不另造重复的通用几何覆盖。
