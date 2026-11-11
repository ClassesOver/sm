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
