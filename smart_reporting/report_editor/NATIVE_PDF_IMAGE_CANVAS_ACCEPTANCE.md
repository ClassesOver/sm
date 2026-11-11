# PDF 待保存图像画布操作

2026-11-10；固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。原始素材为本地Git clone的 `apps/pdf/src/renderer/DrawLayer.tsx`（image、shapeDown/Move/Up、四角handle）与 `src/main/save-pdf.ts` addImageStamp，原vendored引擎保持不变。

选择模式下，待保存image可在画布直接点选、拖动和四角等比缩放，使用与列表相同的完整草稿快照/来源页/精确操作索引。源3 CSS像素拖动阈值、相反显示角固定、dominant-axis比例、显示长边最小16像素、缩放两尺寸均不足2像素时不提交的语义被保留。几何只通过PDF.js viewport正反变换，覆盖旋转、CropBox、UserUnit与CSS尺寸，不另造旋转公式。

连续移动只更新局部SVG与选框，释放时一次折叠回原addDrawing、一次history提交；不每帧序列化整个图片草稿，也不每帧重新渲染PDF。保留原图像数据、相邻记录和既有数值模态/列表操作。来源越界拒绝，不夹取而扭曲比例。

主指针capture绑定稳定SVG与精确pointerId；取消、丢capture、Escape、blur、scroll/wheel、窗口变化、换页、zoom/fit/reflow、草稿变化、预览、保存、销毁或旧DOM均不能提交过期状态。绘图/文字等其他模式及readonly/preview不拦截图片下面的原流程。现有列表和数值位移/缩放仍是键盘可用路径，不宣称四角控制柄具备全部桌面快捷键。

## 草稿与保存显示一致性

原image SVG使用整个页面矩阵，会把图像像素随页面旋转；但固定save writer对image AP反向旋转，原DrawLayer也把图像直立绘在显示bbox。此实现将待保存image改为viewport bbox内直立绘制，其他stamps与几何绘图不改。必须通过非对称四象限PNG的草稿、实际预览与保存重开截图核对，不能只靠文件可打开或AP数字正确认定视觉一致。

## 验证边界

新纯geometry/DOM检查覆盖四种旋转、非零crop、UserUnit2/1.25缩放及CSS比例，四角固定/比例/阈值/非法范围，精确重叠记录、live无草稿写入、释放一次、异指针、取消/失效/卸载与readonly守卫。已有pending/绘图检查一并定向运行，不重复全仓测试。

本次只开放待保存image的直接画布操作；其他几何对象的直接选择/拖动、已保存图像内容编辑、复杂线程/表单设计、全宿主/快捷键/桌面/生产/完整应用镜像验收仍开放。先前PPTX RTL在LibreOffice未镜像列的差异未在此处解决，功能开关保持关闭。

## 本轮结果

- 18项新geometry/DOM检查+9项pending操作+5项绘图检查，共32项定向通过；另加入小图控制柄单击不应触发16px最小放大的回归并复验。几何单测viewport接口使用固定源正反坐标函数构造，覆盖0/90/180/270、非零CropBox、UserUnit2、1.25缩放与CSS尺寸比例；不冒称全部实际PDF.js/设备组合已验收。
- 修复helper在输入数组两个槽位共享同一个对象引用时的索引别名风险，显式拆开目标record，确保精确索引修改不会连带另一个槽位。真实NativeDraft的JSON草稿本身已消除这类别名，此检查保护复用helper边界。
- 生产静态Chromium最终run-2完整通过：真实twins上传、精确选择/拖动/角缩放、live不改draft、释放一次history、阈值、取消/实际lostcapture/Escape/blur/换页/zoom/Undo旧DOM、绘制模式透传、readonly强制CSS命中拒绝，以及刷新/实际预览/告警后下载/保存重开。实际浏览器覆盖DPR2、非零CropBox和90°+反序。
- 非对称8×8四象限PNG在草稿0°、草稿90°、最终缩放草稿、实际PDF.js预览、保存重开五阶段颜色方向完全一致；独立pypdf核验两个Stamp的Rect/BBox/counterrotate cm、原RGB像素哈希、正文/表单/页序旋转。证据 `/workspace/scratch/pr210-image-canvas/browser/evidence.json`。
- 保留run-1失败日志：harness在preview=true但重建未完成时取旧DOM截图，改为等待预览按钮恢复与目标canvas就绪后通过；未为此修改产品代码。
- Standard/Slides最终生产构建、完整前端TypeScript、Standard budget、语法/diff检查通过。只改PDF前端与文档，不改后端、依赖或vendored源码；未重复全仓测试。实际写入走现有Python与打包引擎，鉴权/修订注册为测试替身，不证明生产SQL/鉴权或完整应用镜像。
