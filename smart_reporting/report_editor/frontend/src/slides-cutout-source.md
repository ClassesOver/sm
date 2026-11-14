# CutoutDialog 源码迁移与原生图片替换

固定源 HEAD f8c17004fb730df11f0f743164ffd8b4281bb38c，apps/slides/src/renderer/components/CutoutDialog.tsx SHA256 e9cc007999d4f063f43791f7981c86f15511bdc4eafbeb3bf476c5b3446d5512；renderer/cutout.ts SHA256 3f18ec6e953f9ecc562ae9dc9f19355ec4d6f681d6ddf735ec9963980069cefc。

slides-cutout-pixels.ts 是完整源纯像素模块，保留边缘代表色采样、4连通flood fill、封闭同色区域保留与原图不变。slides-cutout-dialog.tsx 迁完整源容差0–100/默认30/520px预览/透明棋盘/百分比/加载错误/处理中/原分辨率PNG Apply/Cancel；中文取自源panes/zh.ts。宿主替换i18n、图片loader、Esc框架依赖，补原生dialog/焦点/IME、取消后的late decode/定时Apply保护及失败保留预览重试。

固定源picture-edit-actions.ts applyCutout第102–119行通过既有replacePictureBytes keepSrcRect:true保留裁切窗口，因为输出PNG与原图像素几何一致；本地将现有pictureReplacements条目扩展可选keepSrcRect:true并交给同一engine参数。普通ReplacePicture默认仍清裁切，未改其行为。源框架、旋转、层级、边框和效果由既有原生writer保留。

原图只读render-tree内嵌PNG/JPEG dataURL，独立SHA/size匹配当前来源图片；不加载外链、不收客户端路径。打开/Apply核来源SHA、来源页、唯一对象选择、草稿快照、保存/关闭锁和生命周期。Apply走既有单笔NativeDraft、图片字节预算、Python校验与实际PPTX替换保存；取消只丢本地预览。待保存裁切/透明度/替换与结构冲突要求先保存或撤回，避免跨操作覆盖。

源cutout.ts明确TODO“approach B: brush-mark keep/remove regions”；固定源没有画笔和独立撤销重做控件。本轮不增加这些源外功能，不宣称具备。应用后的单笔编辑可以通过既有NativeDraft撤销/重做。
