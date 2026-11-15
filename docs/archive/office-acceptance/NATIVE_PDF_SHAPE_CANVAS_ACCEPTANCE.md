# PDF 待保存几何绘图画布交互

2026-11-10，固定 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`；原始Git clone位于 `/workspace/genoffice`。本次从DrawLayer.tsx drawingShape、shapeDown/Move/Up及edit-ops/ops.ts moveDrawing分支核对，不依据整理后的缺口清单猜功能。

## 范围与来源行为

rect、ellipse、arrow、measure、ink、polygon、caret可在选择模式直接点选并拖动。复用既有来源页/完整snapshot/精确操作索引、3 CSS像素阈值、单次pointerup history、PDF.js正反坐标转换与addDrawing协议；不增加几何resize、颜色或线宽菜单。link不在源moveDrawing有效分支，仍保持列表删除/无画布移动能力。

命中使用源透明粗描边 `max(16,width*scale*4)`，可见形状fill=none；不添加矩形bbox来截获空心图形内部文字。箭头透明头部与可见头部均在同一记录组，ink显示全部paths，caret采用源固定8px显示glyph/1.5px线宽。选中使用不产生额外bbox命中的glow；图像保留既有四角控制柄。

源DrawLayer按全部记录顺序画一个SVG。本次将原先“所有图像先画、其他形状后画”的两层合并为一个按记录顺序的图层，保证image/shape/image交错时视觉与命中顺序一致。legacy image入口保留为共享controller的薄适配，避免复制两套取消/保存生命周期。

只更新当前记录局部live形状，主指针捕获在稳定SVG；释放时验证source/snapshot/index/pointerId/DOM与视口后才提交。取消、丢capture、Escape、blur、scroll/wheel、换页、zoom/reflow、草稿变化、preview/save/dispose沿用既有守卫，其他绘图/文字/只读模式透传。无效或越界位移不裁切/扭曲原形状，也不丢现有草稿。

## 明确保留的视觉差异

本轮保留原Web测量标签按显示线条方向旋转的语义，并将标签与主体同组平移、字号至少9px。固定源UI的label为水平文字，而固定writer AP按PDF线条角度写；三者旋转/翻转的跨阶段视觉并未在此认定全等，须另行核验。caret源UI固定glyph与AP填充楔形也不在本次声明逐像素等价；验证其record point/批注身份与实际输出。

纯坐标检查可以覆盖0/90/180/270、非零crop、UserUnit/CSS比例；真实浏览器与独立pypdf证据需区分，不用“文件能打开”或disabled按钮作为完成证明。原后端、writer、依赖和vendored源码不改。

完整source上下文/快捷键、上述测量/caret视觉差异、已保存对象变换、复杂PDF/表单设计、生产SQL/鉴权、桌面及完整应用镜像验收仍开放，功能开关保持关闭。先前PPTX RTL外部消费者差异未解决。

## 验证记录

- 15项新geometry/render/DOM检查+32项image/pending/drawing相关回归，共47项通过。覆盖七类精确record、live无写入/释放一次、全部ink paths、caret固定glyph、arrow heads/label同组、stroke命中无bbox、image/shape顺序、readonly/失效/越界，以及0/90/180/270与非零crop/UserUnit2/CSS比例的viewport接口检查。
- 实际Chromium shape闭环覆盖DPR2、非零CropBox、90°+反序，真实鼠标在可见stroke旁4CSSpx命中透明stroke、ink第二path、精确twins、单次撤销/重做、三点交错image/shape/image命中、empty rect/ellipse内部透传、取消/丢capture/Escape/blur/换页/zoom/旧DOM、其他模式/只读、实际预览/告警后下载/保存重开。
- 独立pypdf回读11条record顺序及L/InkList全部paths/Vertices/Rect/caret point、measure Contents/Tm/AP，原批注AP哈希、正文/表单及旋转页序均保留。source fixture不变，真实Python与打包writer写出；鉴权/修订登记路由仍为测试替身。
- 原image画布完整浏览器回归同时通过，保留五阶段四象限RGB同方向、原PNG像素哈希与几何、角控制柄/取消/历史/只读隔离证据。
- 首轮shape harness的屏幕→源坐标比较1e-5阈值低于SVG float32精度，出现1.1097e-5源单位误差；仅将该比较容差调整为1e-3 PDF单位（仍小于writer0.01精度），文件几何按实际writer精度另核。保留run-1失败记录。
- Standard/Slides最终构建、完整前端TypeScript、Standard budget、语法和diff检查通过；首轮构建曾读到新SVG属性union类型待修复，显式类型注解后最终通过。无后端/依赖/vendored变更，未重复全仓测试。

证据目录 `/workspace/scratch/pr210-shape-canvas/`，shape与image回归证据分别在 `browser/evidence.json`、`image-regression/evidence.json`；原始素材与未完成视觉差异一并保留，不宣称完整PDF/Office对齐。

最终shape run-3进一步逐坐标验证两箭头头部x1/y1/x2/y2随主记录平移（不只统计节点数），measure标签x/y随动也单独核验。run-2产物另存以免覆盖，全部失败/成功日志保留；未为此修改产品代码或重新构建。
