# PPTX Normal幻灯片栏键盘导航设计

## 证据与意图
固定源 GenOffice f8c17004 apps/slides/src/renderer/keyboard-actions.ts:328起，在无对象选中且rail焦点时支持ArrowUp/Down、PageUp/Down及Home/End；方向键按当前页位置clamp，Home/End首尾。当前本地Normal栏slides-main.ts::renderSlides仅创建.slide-open点击事件；全局onClipboardKey只接保存/打印/剪贴板，未接这些导航键。Sorter已有独立处理。本切片补Normal栏直接页按钮焦点时的导航，保留PC键盘操作，不扩canvas/对象/多选行为。

## 方案
建议独立小型delegated-list控制器，监听已有.slide-list，按selectedSlide在最新DOM页按钮序列的位置计算，而非Tab聚焦按钮；仅next不等于current时调用目标.slide-open现有同步click路径，之后selectedSlide===target才重新查询并focus({preventScroll:true})/scrollIntoView({block:nearest,inline:nearest})。原click中的notesPane.flush→selectedSlide→renderSlides→renderInspector顺序完全不改；否决不主动移焦，保留flush自身错误焦点。边界消费但不click/flush。共享openSlide布尔提取为讨论过的备选，按root最终裁定不采用。避免renderSlides重建DOM导致失焦；无需第二套状态、保存或解析协议。将键盘导航内联global handler会扩大作用域并干扰其它view，不采用；复用Sorter多选控制器会带入不需要的选择/拖排事务，不采用。

## 精确边界
只接实际直接聚焦.slide-open按钮的未处理普通keydown。忽略ctrl/meta/alt/shift（本切片不实现范围选择）、IME/isComposing/keyCode229、非Normal、disabled/隐藏按钮、列表管理按钮、输入/dialog及来自别处的事件。按最新DOM中的.slide-open顺序（对应order）而非source slideIndex计算；包含隐藏页及未保存新页，与现有普通点击一致。可在边界按键后保持焦点但不重复点击。notes.flush拒绝导航不改当前页且不覆盖它设置的错误焦点；成功冲刷脏备注可能产生既有点击路径同样的草稿修改，不能宣称永远零草稿。无脏输入时导航不改草稿。click本身无返回值；因next必须不同于原current，现同步click后的selectedSlide===target是本切片的成功信号；若点击变异步必须重新审查。locked状态不一刀切禁用只读导航。保留native ol/button与Tab顺序、CSS；aria-current标真实当前页，不引入listbox role。其他编辑能力不变。dispose移除监听。不接真实Codex、不改AI/替换/PDF/#236，不推送/PR/合并/部署。

## 验证
TDD DOM控制器用例：最新重排/非连续ID/首尾clamp/重复按键后DOM重建焦点/notes否决、IME/修饰键/defaultPrevented、嵌套编辑/管理按钮/非Normal、dispose。集成DOM测试调用真实slides-main fixture，断言当前页与按钮焦点、无脏输入时草稿零变化与请求零保存；另验脏备注flush成功与失败保留错误焦点，Tab聚焦页与selected不同也按selected计算；已有相关视图专项定向回归，不重复全套。条件允许补浏览器真实rail操作，但不将jsdom称像素或真实保存验收。本功能只改视图状态，不需改PPTX或生成保存回执。

## 状态
Astra已独立核固定源，root已批准按selected计算及click复用的最终窄方案。实现及验证状态见同日验收记录，不以本设计文档冒称浏览器或完整构建通过。
