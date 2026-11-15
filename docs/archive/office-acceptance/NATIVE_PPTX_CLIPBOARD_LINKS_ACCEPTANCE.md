# PPTX 内部对象剪贴板、格式刷与对象超链接验收

日期：2026-11-11。固定 GenOffice 来源 commit：
`f8c17004fb730df11f0f743164ffd8b4281bb38c`。

## 交付范围

- 内部对象剪贴板：复制不写历史；剪切复用来源对象删除；粘贴只提交同文档、同来源SHA的对象引用与偏移。普通顶层文字、形状和嵌入PNG/JPEG按来源能力开放。
  来源为已保存基线；剪贴板仅当前会话驻内存，刷新不恢复，但粘贴草稿可恢复。新对象保存并重开新修订后显示和编辑。每次粘贴偏移20px，最多50条、共500对象。
- 跨页粘贴要求母版、主题路径一致。布局重置、版式切换、相关页组合/复制/删除以及全局主题/尺寸/页眉页脚修改保守拒绝。服务端先捕获来源XML和媒体依赖，删除后仍可恢复；不接受客户端XML/parts/rels。末尾按目标part path定位，使用固定源copyElementData/pasteElements。
- 格式刷：单击一次、双击连续、Esc退出；一次有效应用一个历史步骤，无变化不写历史。只复制明确且统一的字体字段、对齐、形状填充和边线。字体名称仅在所有非空run的latin/ea/cs三槽明确且同名时复制；混合、主题引用或继承缺省字段省略，不把显示用fontFamily或首run当作整对象格式。保留正文和其他草稿，不刷列表/行段距/几何。
- 对象超链接：普通顶层文字、形状、静态图片支持HTTP/HTTPS/mailto、来源页跳转和清除。保留ScreenTip与hover；按来源part path和唯一SPID重定位，使用固定源setElementLink。段内链接、复杂动作或歧义关系只读，避免原生setter删除段内链接。当前本地静态放映不执行链接，对话框已明确提示。
- 接入NativeDraft、Undo/Redo、刷新恢复与新修订保存。来源或草稿改变时拒绝陈旧链接对话框。输入框保留浏览器复制粘贴，非原生模式不拦截对象剪贴板快捷键。

## 定向验证

证据目录：`/tmp/pptx-clipboard-links-20261111/`。

- Python协议28项：有效转发、schema/索引/限额及外部原始数据拒绝。先RED，25项GREEN后修正_slide_index布尔判定，仅窄复验余下3项通过。
- 真实后端6项通过（backend-green.log）：真实inspect/patch、媒体/裁切、切后粘贴、重排映射、URL/移除及非法输入原子拒绝；旧bundle先5失败/1通过。
- 剪贴板前端原4项和跨master/theme新增1项；bridge原6项、跨链新增1项和目标rels新增1项通过。合法XML闭标签`</Relationships >`在原生字面追加中会静默丢图，现prepare/apply前只读拒绝；新增回归先RED后GREEN并验证失败不改ZIP和对象，未自写OOXML修复器。
- 格式刷前端6项、bridge5项通过；明确/混合值与真实解析已覆盖。超链接前端5项、bridge原6项及形状/裁剪图片保真新增1项通过，非链接XML、媒体、裁切与几何保持。
- Ribbon原28项及新增2项通过。主集成原4项、边界新增5项、审查修复新增2项通过；后两项先RED后GREEN，覆盖已有来源链接直接确定不制造草稿、legacy快捷键不被吞。
- helper严格TypeScript和集成bridge严格TypeScript通过，最终bridge bundle成功；Python相关文件ruff通过。未重复完整测试。

## 构建及待完成验收

主Vite构建43.78s、slides子应用51.05s、management子应用7.84s成功；独立冻结目录为
`/tmp/pptx-clipboard-links-20261111/static-final`。827个文件、347个主assets JS，
主PPTX包237173字节，保持既有250KiB上限。清单SHA256为
`3d117984740b3c7ddb9a2f451f4c7468d93c3ec4e1f286ef746e4be3bebef3c5`。

首次真实浏览器在修订2独立回读发现字体问题：来源仅声明latin=Arial、中文字体继承Calibri，
解析模型的fontFamily为显示用Calibri，原摘要误当明确字体。失败证据保留在browser.log、
browser/source.pptx、browser/revision-2.pptx；不得把此轮误标通过。修复应省略不具备
明确且统一latin/ea/cs声明的字体字段，不能用显示字体覆盖来源的多文字体系继承。
现已改为所有非空run的三槽明确同名才提取字体。目标RED 2项按字体未省略断言失败，
修复后新增3项GREEN，包含真实PPTX保存再读、三槽Arial正例及混合/主题/继承矩阵；
最终严格TypeScript通过，未重跑旧5项。日志为brush-font-slots-{target-red,green,strict}.log。
独立读取初轮真实source.pptx确认不再摘要错误字体，见brush-original-source-probe.json。
最终往返夹具为三槽同名明确来源，保留保存后完整字体比较，并先断言摘要A=Arial、B=Calibri。
仅重新bundle后端，未改冻结的前端文件；最终edit-pptx.mjs SHA256为
`d56de74af46598d9e47e8bfdabcdf8f50bb7e98c1b87786c50a7396c5eba22dd`。

全目录TypeScript仍有其他在途文件错误（frontend-types.log）：PDF SectionSettings、
Word vendor依赖、workbook protection/main/sparklines，共13条；未修改无关代码。
全局预算仍有4项超限：native-docx-render 788.8/710KiB、pdf-main 256.7/250KiB、
workbook-engine 439.8/428KiB、workbook-main 263.1/253KiB。未提高预算。
上一批501次段落压力场景仍超时，未通过且未重跑；本批不能据此声称全前端检查全部通过。

## 最终浏览器往返验收

2026-11-11 13:35（Asia/Shanghai）最终Chromium验收exit0，完成真实修订2–4。
证据为browser-final.log、browser-final/evidence.json与final-verification.json。
使用显式授权/CSRF路由fixture，实际执行Python inspect/patch/render及独立python-pptx/ZIP回读；
不覆盖生产认证、真实PDF转换及原生PDF插件，辅助PDF iframe为有效附件占位。

验证路径：复制图片不落历史→A刷B→Undo/Redo→After对象设置含`$&`及amp query的精确URL
→跨页粘贴→Undo/Redo→刷新恢复（内存剪贴板不恢复）→保存/下载/修订2重开
→剪切来源图片立即隐藏→跨页粘贴→刷新恢复→保存/下载/修订3重开
→移除已有对象URL→保存/下载/修订4重开。

独立回读确认目标正文不变、字体/字号/粗斜体/下划线/颜色/对齐/填充/边线正确，
图片媒体字节与裁切不变、偏移正确、SPID唯一；剪切后来源图消失、目标图数量增加；
URL逐字保持并最终清除。除允许的目标slide XML与rels外，所有ZIP部件SHA保持。
root目视revision-four.png确认B格式与A一致、来源图已移除。

冻结前后827个静态文件及4个服务端桥包逐个SHA/大小完全一致；浏览器实际加载113个JS，
均与冻结文件身份一致；page/console/route/HTTP错误数组均为空。

下载实物身份：

- 修订2：42908字节，SHA256 `09659499f9643f88d2d60d4a21eed9365740336beb0814e5bbea7c6ad01dc519`。
- 修订3：42767字节，SHA256 `7c1ba7b1b48d83098055ed35046d1b2174eed08344ead95edbbbcf5db4267333`。
- 修订4：42679字节，SHA256 `a0c55178890a45b41699f10669c563d5e1dfb6a96406346f41b7d7933b583de7`。

本批受限能力通过最终验收；上文全目录类型、全局预算、旧压力场景及下列对齐项仍开放。

## 仍开放的对齐项

- 系统剪贴板、跨文档复制及外部文本/图片粘贴，粘贴后保存前的新对象编辑。
- 混合run格式、分文字体系字体、复杂对象/组内对象的完整格式刷；段内链接与复杂命名动作。
- 动画、转场及音视频的真实播放，链接交互放映、演讲者视图、排练计时和录制。
- 复杂/嵌套组合、母版编辑、演讲者备注和复杂图表格式。
- 功能区内打印、PDF/图片导出、另存为、公式/墨迹及音视频/3D插入等未开放入口。

本增量不等于与GenOffice全面对齐，未提交、推送或部署。
