# PDF 待保存图像等比缩放

2026-11-10，固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。

原始素材：App.tsx:2991 resizeDrawing→setDrawingRect，edit-ops/ops.ts:317只替换image记录的rect；DrawLayer.tsx:480–531的角控制柄以相反角固定并保持纵横比。它不是任意PDF已保存图像编辑或自由拉伸。

Web 在已有待保存绘图精确选择面板中，为image增加百分比与固定角模态。固定角明确采用未旋转PDF坐标，保持当前rect纵横比；属于源缩放行为的数值交互适配，不声称桌面拖拽/控制柄等价。保持原image字节、其他字段和相邻记录，仅将新rect折叠回原addDrawing。

来源页/完整草稿快照/记录索引与单一modal身份绑定；非image、失效选择、NaN/无穷/零或负比例、尺寸/坐标越界、取消/替代/过期弹窗、只读/保存/预览/销毁回调必须拒绝，不夹取而改变形状比例。

已有历史、刷新恢复、真实预览和下载重开沿用。独立文件验证需同时核对Stamp批注边界、AP内部图像几何/图像数据及正文/表单/其他批注；不能仅凭文件可打开判定完成。

后端协议、固定writer和vendored源码不改。源直接画布控制柄、已保存图像内容编辑、完整宿主/桌面/生产/镜像验收仍开放，功能开关保持关闭。

## 定向验证

4项新增resize检查+5项已有pending操作+5项绘图检查共14项通过，涵盖四角等比/图像字节与相邻记录、非image/非法数值/超界/陈旧引用拒绝、历史/刷新，以及小数边界固定角不因浮点加回越界。完整前端TypeScript通过。

生产静态Chromium首次run-1完整通过：实际上传两相同PNG，精确选第二张按右上固定角缩50%，第一张不变；拒绝超界/负比例/取消/替换/失效modal，历史/刷新，90°旋转和反序，实际预览、验收告警后仍下载、重开、readonly强制绘制均验证。独立pypdf检查两个Stamp的Rect/BBox、逆旋转cm矩阵与相同4×2 RGB像素哈希，正文/表单及页序保留。证据 `/workspace/scratch/pr210-cell-image/pdf-browser/evidence.json`。

API鉴权/修订注册为测试替身，PDF写入使用真实Python服务与打包引擎；不证明生产SQL/鉴权或完整应用镜像。

Standard与Slides生产构建、完整前端TypeScript、配置的Standard budget、Python应用Ruff、语法与diff检查通过；未重复完整仓库测试。原始vendored引擎、依赖/锁文件与PDF后端协议未改。
