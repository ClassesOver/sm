# PDF 草稿测量与 caret 按实际 AP 对齐

## 范围与来源

本批为本地 SVG 草稿一致性适配，不是声称补回固定源漏实现。只读核实 `/home/junge/pros/genoffice-source-full` HEAD 为 `f8c17004fb730df11f0f743164ffd8b4281bb38c`，相关源文件无工作树改动：

- `apps/pdf/src/renderer/DrawLayer.tsx`：测量标签 `textAnchor="middle"`，`Math.max(9,9*scale)`，原源标签不旋转；caret 为固定CSS尺寸、开口、无填充的V。
- `apps/pdf/src/main/save-pdf.ts`：测量标签9pt Helvetica，舍入至两位小数的PDF角度矩阵，从线中点加PDF y=6的位置起写；caret为PDF点尖端及x±8/y−6顶点组成的填充三角。注释标志F=4，没有NoZoom。
- 本地旧 `pdf-drawing-shapes.ts` 已增加标签显示角旋转，但仍居中、最小9px；caret仍为固定CSS尺寸开口V。

此前真实浏览器证据 `/tmp/pdf-label-required-slots-text-browser/interleaved-draft.png` 与 `mixed-preview.png` 明确显示草稿居中/开口V和实际AP中点起写/填充三角差异。未启动上游Electron桌面应用；源UI结论来自该固定提交源码，本地UI结论来自现有真实浏览器截图。

## 最小实现

只修改 `frontend/src/pdf-drawing-shapes.ts` 的measure/caret显示分支，保留原生writer、协议、AP BBox、字体资源及绘图操作数据。

测量标签先在PDF坐标求与writer一致、实际舍入后的六值Tm `[a,b,c,d,e,f]`。记viewport映射为V，令O=V(e,f)、U=V(e+a,f+b)、D=V(e−c,f−d)，则SVG矩阵为 `[Ux−Ox,Uy−Oy,Dx−Ox,Dy−Oy,Ox,Oy]`。这是 `viewport ∘ Tm ∘ diag(1,−1)`；最后一项转换SVG字形向下的y轴，不能把PDF的y轴直接用于SVG。viewport已包含旋转、缩放、CropBox和UserUnit，不重复乘scale。

SVG text固定9字体单位，起点0/0，start锚点、alphabetic基线、Helvetica/Arial/sans-serif回退；关闭kerning与ligatures以贴近literal Tj。caret三个实际舍入PDF顶点分别经过viewport，再闭合填充；透明16px hit轮廓和原有移动事务保留。

## 已完成的定向验证

- `frontend/src/pdf-drawing-appearance.test.ts`：真实RED 40/40失败（原居中锚点、无填充caret）；最小实现后40/40通过；随后真实Chromium探针发现font-kerning/font-variant-ligatures的SVG属性形式被忽略，补充CSS属性RED后改为style属性，最终41/41通过。证据 `/tmp/pdf-drawing-appearance-red.log` 与 `/tmp/pdf-drawing-appearance-green.log`；最终 `/tmp/pdf-drawing-appearance-css-{red,green}.log`。
- 水平、实际num2斜线、反向、竖直四种实际AP Tm，覆盖0/90/180/270°、zoom0.5/2、非零CropBox和UserUnit2；通过多个字形空间点验证原生Tm到SVG映射。独立caret顶点、填充、透明hit及操作数据未变均覆盖。
- 仅同步既有canvas渲染单项预期；定向执行该项及measure/caret移动事务共3/3通过，其余12项跳过。证据 `/tmp/pdf-drawing-appearance-affected-green.log`。
- shapes及新增test窄strict tsc exit0，证据 `/tmp/pdf-drawing-appearance-types.log`。
- 专属 `frontend/smoke/pdf-drawing-appearance-checkpoint.mjs` 的 `verifyDraftDrawingAppearance(page,{directory,sourceSha256,staged})`，供共享文字smoke按 `PDF_DRAWING_APPEARANCE_SMOKE=1` 接入（同时开原水平bounds变体）。只通过真实UI将zoom切到0.5/2/1，固定核对水平AP对应矩阵、caret填充顶点、透明hit、computed字体CSS和未变草稿，逐步写 `draft-appearance.json` /截图。
- 专属 `frontend/smoke/pdf-drawing-appearance-verify.py <directory>`，独立读下载mixed.pdf实际Tm/caret指令，对照上述checkpoint。浏览器本批仅0°×多zoom；quarterturn/CropBox/UserUnit仅限单元验证范围。实际浏览器和下载AP对照现已由root统一运行，通过结果见下节；浏览器覆盖不扩大为所有旋转、CropBox和UserUnit。

## 真实浏览器证据

本批真实生产资产浏览器专项通过，证据目录 `/tmp/pdf-ap-arrange-links-text-browser/`，总结果 `summary.json` 的 `ok=true`。Chromium为140.0.7339.16，固定manifest SHA256为 `8c79637a9733aeefbbd248d7754b9fcc9b0b898bf5144c2c81078eda83519451`。37份实际加载JS资产与冻结磁盘SHA逐一相等，pageErrors、consoleErrors、httpErrors、assetErrors均为空，来源文件未变。

- `summary.json.draftAppearance` 与 `draft-appearance.json`：真实UI依次切换zoom0.5、2、1，页面尺寸分别150×200、600×800、300×400；各步五项草稿操作完全相同，结束回1倍。
- 固定场景为0°页面，`3.00 m` / `0.04 m` 实际AP Tm分别 `[1,0,0,1,160,206]`、`[1,0,0,1,81,306]`。1倍SVG矩阵分别 `[1,0,0,1,160,194]`、`[1,0,0,1,81,94]`，0.5/2倍按同一viewport变换对应，字号仍为9个字形单位、start锚点；实际computed CSS的kerning和ligatures均为none。
- caret实际PDF顶点为 `(255,300),(247,294),(263,294)`；1倍SVG为 `(255,100),(247,106),(263,106)`，0.5/2倍随viewport变化；闭合、填充色、无可见描边及透明16px hit轮廓均通过。`summary.json.appearanceIndependent` 由专属Python脚本独立复读下载AP Tm和caret路径并与浏览器JSON对应，`ok=true`。
- 截图为 `draft-appearance-0.5.png`、`draft-appearance-2.png`、`draft-appearance-1.png`；实际PDF预览、保存、下载及重开成功，修订4→5，登记成功，重开文件身份与下载一致。`mixed.pdf` 为14434字节，SHA256 `f10f2ca10f317129b8f90e032e31fb27802f870108253c65a3684d3c6fbea5d8`。
- 既有独立BBox诊断在600×800渲染中差异0像素；该比较是**实际PDF与扩大BBox诊断PDF**，不是SVG与PDF字体逐像素同源证明。

上述通过的是限定场景的结构、原生矩阵到SVG变换、caret几何及编辑交付链路。保存响应仍诚实返回 `validation.ok=false`，保留业务内容/完整版式待复核及字体回退、页边裁切告警，同时正常签发下载；本批未把该响应改标验收通过。

## 限制

不同系统的Helvetica回退字体与PDF.js Standard14替代字体，字形像素及advance不保证完全相同。该适配明确保证原点、基线方向、字号尺度和caret顶点/填充遵循原生AP，而不强制SVG与PDF渲染逐像素相等。页面CropBox仍可能裁切页边长标签。源UI与实际AP本来就不同；本批选择按实际AP显示本地草稿。无OCR。

最终 root 已目视实际1倍草稿与下载PDF渲染，标签中点起写和caret填充三角的几何对应；未将草稿中尚未应用的原文字预览与保存后样式改字内容要求像素全等。统一范围和证据见 NATIVE_PDF_AP_ARRANGE_LINKS_ACCEPTANCE.md。

## 2026-11-11 字体与四旋转组件专项补证

本节补足上文仅0°实际浏览器、字体由系统回退的边界；此前完整保存/下载/修订链路证据保留。本批产品改动仅在PDF绘图模块：导入专属 `pdf-drawing-font.css`，以 `PDF Standard Helvetica` 字体别名加载已部署的 PDF.js `standard_fonts/LiberationSans-Regular.ttf`，后接显式 `Liberation Sans, Helvetica, Arial, sans-serif` 回退；不复制字体、不改writer、AP字体资源或全局PDF.js配置。字体使用 `font-display:swap`，measure仍为9字体单位、关闭kerning/ligatures，补充 `text-rendering:geometricPrecision`，避免Chromium在0.5倍下对SVG advance按设备像素取整。首轮真实浏览器观察到同一文字SVG advance为66、连续字体度量64.5249，补充后为64.53125。

锁定 `pdfjs-dist@6.2.108` worker的Standard14表映射Helvetica到该TTF，但产品 `getDocument` 使用默认 `useSystemFonts`，不能据静态映射声称实际AP必定使用资产字体。新专项使用与产品相同的legacy PDF.js入口及默认加载参数；本环境实际 `FontFaceObject.systemFontInfo.css` 为 `"Helvetica",g_d0_sf2,sans-serif`，系统替代face为loaded，度量与显式资产别名一致。仅证明该环境实际路径匹配，不推广到所有客户端或所有PDF字体。

真实探针为 `frontend/smoke/pdf-drawing-font-smoke.mjs`，证据 `/tmp/pdf-drawing-font-browser/summary.json` 的 `ok=true`，Chromium `140.0.7339.16`。它通过Python原生 `patch_pdf` 写出真实measure/caret AP，再由pypdf独立提取实际Tm、Tf、Tj、Helvetica资源及caret路径；esbuild仅把实际 `paintDrawing` 和产品同款PDF.js入口编译到 `/tmp` 作为组件夹具，不使用另一套SVG绘制实现，也不改共享生产static。

- 0/90/180/270° × zoom0.5/2共8个真实浏览器场景，均含水平、实际两位小数Tm斜线、反向、竖直四标签及caret。原生AP→viewport→SVG矩阵、caret三顶点/闭合/填充全部通过；SVGMatrix的float32比较容差为0.00005。
- 字体资产在浏览器实际加载，SHA256 `f8ace1f892b2bd9dc1792ba7f097fa7588f84fed48321480e04de5390828221f`；已发布static与锁定npm包TTF字节相等。32标签的SVG advance与实际PDF.js系统替代CSS advance最大差 `0.01220703125` 字体单位。
- 完整实际AP与草稿并排截图为 `compare-{rotation}-{zoom}.png`，各自整页图为 `draft-*` / `saved-*`。为隔离与竖直文字重叠的测量线，另从实际AP只保留原始rg/BT/Tf/Tm/Tj/ET、字体资源、BBox及注释几何生成 `saved-labels.pdf`；不扩大BBox、不改矩阵或字形。`pdf-drawing-font-verify.py` 独立Pillow检查32组label-only栅格墨迹边界，ROI由pypdf Tm和实际PDF字体advance形成的宽松字体框与SVG框取union再扩边；两图墨迹均不得碰裁剪边界。通过阈值为每边差不超过2个CSS像素，实测最大1像素，证据 `visual-independent.json`。该诊断不要求抗锯齿像素、墨迹像素数量或所有字形轮廓完全相等。
- 字体请求故障注入实际阻断TTF，`font-load-failure-fallback.png` / `fallback.json` 显示别名字体status=error，但回退文字可见且bbox宽 `60.0283203125`。当前环境原Helvetica/Arial/generic sans度量为0、显式Liberation Sans可用，因此保留其作为第一系统回退；不声称其他客户端原回退都存在此问题。
- 本次合成来源SHA256 `41ca0ee1d6ec3a96190266e38063a2c20b7a9cea652eb73f395d461f62244077`；当前writer实际输出SHA256 `0908e3116366a1198e4afbbcff4a1a932644af7179d4ecda95b0370358c51e28`。正常8场景page/console/server错误为空，故障注入预期的字体请求失败另列。
- 最终窄回归 `pdf-drawing-appearance.test.ts` 41项、`pdf-drawing-canvas.test.ts` 15项、`pdf-pending-drawings.test.ts` 9项，共65/65通过；两份新增mjs语法检查与 `git diff --check` 通过。root统一构建实际Vite产物包含最终字体链、geometricPrecision及可部署的既有TTF URL，全部JS预算检查通过；未另外重复构建共享static。

本地首次运行发现忽略目录 `pdf_engine/dist/cli.mjs` 仍是11月10日旧包：水平AP BBox为 `[37,317,243,329]`，竖直为 `[67,37,73,143]`，实际裁切字形，故视觉检查失败。当前source已有 `measureLabelBounds` 修复；安装lockfile依赖并重建本地bundle后才取得上述成功，不把重建缓存冒充新增writer修复。失败旧输出及独立BBox记录保留于 `/tmp/pdf-drawing-font-old-bundle.pdf` / `.json`。

本节是实际writer + PDF.js + 实际绘图组件专项，不新增完整产品保存/下载端到端证明；CropBox/UserUnit继续只有上文单元范围，未升级为本节实际浏览器覆盖。页面边缘裁切、外部客户端系统字体差异及其他字体仍保留限制。全局PDF.js默认字体选择策略未修改。


## 2026-11-12 CropBox / UserUnit 与绘图线宽补齐

本批补齐上一节仍缺的**限定组件浏览器场景**，并修复实际显示缺陷：`pdf-main` 传入的 scale 只是缩放倍率，旧 `paintDrawing` 以它计算线宽和箭头头部，遗漏 `/UserUnit`。UserUnit=2、zoom0.5、实际AP线宽1时，旧草稿线宽0.5，保存后为1；文字/坐标已经按viewport放大，导致同一绘图内部尺度不一致。前轮新增8项窄回归均先失败（其余41项通过），实际浏览器线宽对照也复现0.5≠1。

现在以实际viewport的 V(1,0)−V(0,0) 距离取得PDF用户单位到显示坐标的比例，统一用于可见线宽、箭头头部及透明命中轮廓的粗线比例；命中最小16 CSS px与caret命中轮廓保持。保留旧第四个参数作为调用兼容，但不再把它当成用户单位比例。矩形、椭圆、手绘、多边形、测量线和箭头均覆盖；不改变原操作坐标、标注宽度数据、writer、AP或保存协议。

### 实际来源与独立验证

- 新 fixture `PDF_DRAWING_FONT_GEOMETRY=crop-userunit`：独立pypdf生成 MediaBox `[0,0,500,600]`、CropBox `[30,40,430,440]`、UserUnit=2。操作仍是PDF用户坐标，只按CropBox原点平移，不预乘UserUnit。真实引擎接受，输出由pypdf确认完整保留原MediaBox/CropBox/UserUnit。
- `/tmp/pdf-crop-userunit-20261112/summary.json`：ok=true；0/90/180/270° × zoom0.5/2共8场景。实际PDF.js page.view与独立CropBox一致，viewport宽高与UserUnit、旋转、缩放一致。pypdf从实际AP读出w，逐项核对SVG可见测量线宽等于AP w × viewport单位长度；zoom0.5为1px、zoom2为4px。
- 同一8场景的实际Tm、字体、caret顶点/填充均通过；32标签独立文字诊断栅格边界最大差1 CSS px，沿用前节独立union ROI与无触边检查，不声明抗锯齿或所有像素相同。字体失败回退仍可见；正常场景page/console/server错误为空。root独立复核JSON、实际PDF文件SHA，并目视90°/0.5倍并排图。
- `/tmp/pdf-default-stroke-20261112/summary.json`：默认CropBox/UserUnit1再验8场景通过，32标签最大边界差1px，确认普通来源未回归。本轮两种来源合计16场景，不推广到所有PDF来源。
- 证据目录已改为必须新建；复用已有目录会在生成前EEXIST退出。实际故障注入核对旧summary SHA不变，避免后续复跑覆盖旧证据。
- 恢复工作区后，3文件73项定向通过：appearance49、canvas15、pending9。完整 `npm run build`（Node heap4GiB，含tsc）通过，Vite45.90秒；全部JS预算通过。日志 `/tmp/pdf-userunit-tests-20261112.log`、`/tmp/pdf-userunit-build-20261112.log`、`/tmp/pdf-userunit-budget-20261112.log`。没有重复完整项目测试。

### 页边长标签仍开放

独立真实探针 `/tmp/pdf-edge-label-20261112/summary.json`：同一CropBox/UserUnit2，页内测量线 `[330,200]→[410,200]`、64个W的标签，实际AP BBox为 `[327,197,917.248,217.379]`，超过可见页框右界430。引擎实际生成文件，appliedOperationIndices=[0]，没有跳过操作；此普通测量路径的reviewIssues为空。扩大AP BBox避免标注自身误裁，不会扩大页面CropBox；页边长标签仍会被可见页框裁切，本批没有移动/缩小标注或修改页面来掩盖它。需要后续明确的页边风险提示或用户可控排版，不能把本轮线宽/字体对齐计作该项完成。

本批仍是实际writer + PDF.js +实际绘图组件验收；不新增完整产品保存/下载/生产宿主端到端证明，也不表示所有UserUnit相关编辑、测量标定或跨页行为均已验收。未改发布签发链、未部署或开启功能开关。
