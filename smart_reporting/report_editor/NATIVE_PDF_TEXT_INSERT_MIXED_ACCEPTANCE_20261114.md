# PDF 原位改字与静态新增文字组合验收（2026-11-14）

本批支持同一草稿的 replaceText + insertText（普通/样式/手动多行），包括多次插入、跨页插入及原索引交错。复用既有改字writer和静态插入writer：原始来源先校验全部新增位置与安全能力，再改原对象，最后由引擎重绑中间SHA进行插入。回执和previewDigest始终绑定原输入/原SHA/最终实际字节；后段故障保留已生成产物并诚实给出跳过索引。不新增路由、依赖或签发步骤。

## 定向和故障验证

- /tmp/pdf-text-insert-mixed-engine-final.log：21通过（6个本批组合、15个既有静态插入）。覆盖实际文字/字体/页序、确定性摘要、操作数组不变、错误SHA/落点零写入、stale replacement跳过仍保留新增、插入加载异常保留改字和原索引。新测试已登记引擎package.json的test命令。
- /tmp/pdf-text-insert-mixed-front-reviewed.log：10文件71通过；新增fixture仅类型推断修复后，该文件2项再次通过，见fixture-final.log。涵盖两个公共原位改字入口、两种操作顺序、管理/预算、过期回调和已支持标注/矢量/PNG/链接/测量组合邻接。
- 旧drawing拒绝fixture中安全https链接在HEAD也被允许，独立基线测试日志baseline-link.log证实；临时测试/原验证器副本已删除，原拒绝fixture改为javascript目标，不改产品协议白名单。
- /tmp/pdf-text-insert-mixed-service.log：只运行新增的3操作参数，1通过6未运行。实际NativeEditorService/隔离CLI/预览确认/保存修订/下载流，下载字节等于实际预览；pypdf确认Amount due 750和两段新增文字，原500消失，控制文字及源文件保持。仓储/下载设施是既有内存fixture；不是生产HTTP授权验收。
- /tmp/pdf-text-insert-mixed-build.log：实际隔离CLI构建成功，路径/tmp/pdf-text-insert-mixed-runtime/dist/cli.mjs，复用安装依赖；未写shared dist/static，不是自包含发布包。

## 实际浏览器

PDF_TEXT_INSERT_MIXED=1 AGENT_REPORTING_PDF_ENGINE_DIR=/tmp/pdf-text-insert-mixed-runtime 执行 smoke/pdf-pending-text-smoke.mjs；证据根/tmp/pdf-text-insert-mixed-browser，日志/tmp/pdf-text-insert-mixed-browser.log。实际源码pdf-main/真实PDF.js/实际来源检查模型；Edit页签入口完成改字，与既有新增组成insert-first.json的[insertText,replaceText]，再删除新增留下改字，重新插入组成最终[replaceText,insertText]。管理窗口编辑/删除、Undo/Redo、重载恢复和390×700截图仍经过实际DOM。

最终草稿实际CLI写出edited.pdf，applied=[0,1]、skipped=[]。独立pypdf读取Changed original及Updated second，不含旧Original preserved、被删First inserted或旧Second inserted。独立回读矩阵基线[160,220]、字号14，详见independent-baseline.json。实际PDF SHA256=cb05ea36197d31b3df2ef2cfc74472420d55e0ed6c8b99b018bd74b7a2e1411b。源文件SHA不变。manager-narrow.png已目视；宽356、scrollWidth356、left16，编辑窗口纵向滚动保留。pageerror及HTTP>=400均空。

Vite源码依赖扫描仍有其它格式fast-xml-parser/saxes/utif2解析提示，未隐藏。最终全局tsc退出2，日志types-final.log与上一批逐字节相同（632条既有诊断），无本批PDF诊断。引擎独立tsc试验也未通过（旧PDF图像/operations类型、Process.resourcesPath及固定源类型包缺失等），无text-insert-mixed/static-text诊断；不声明严格全局构建成功。git diff --check与烟测脚本语法检查通过。

## 剩余边界

仅两种文本操作可组合；插入来源仍不接受批注、表单、保护及非默认单位等复杂源。新增文本不随原文自动reflow，也不支持与页面结构/绘图/标注等任意混用。源文字块移动、段落编辑/自动重排、跨对象游标、主画布即时预览、完整AI工具及外部证书服务等仍开放。浏览器为Vite源码适配器，未跑生产静态包/HTTP保存；服务保存下载是独立fixture验证，不混称同一条完整生产浏览器链路。未提交、部署或开启功能开关。穷尽PDF缺口目标保持active。
