# PDF 原文字对象移动增量验收（2026-11-14）

新增moveText操作和原位改字区的“移动原文（保留字形）”控件，以原PDF用户坐标填写X/Y位移。操作绑定原SHA、页、文字对象和原文摘要，复用固定源TextEditInput.translate对原对象做变换，保留字形/字体/字号；没有擦除后重插。支持多个独立对象跨页移动、逐次Undo/Redo/持久草稿恢复、0位移撤销该对象草稿。移动草稿与改字/插入/页面/表单等其他种类暂不混用。

来源仍限静态文字的安全范围：无表单/保护/批注、默认页面单位；只移动可唯一匹配的整对象，目标需在CropBox内。重复/歧义/伪造来源/非法目标在写入前拒绝。固定源匹配验证还检查共享模板及whole匹配。实际输出复核全部文字/字体/字号/预期矩形和非目标对象，以及页数、MediaBox/CropBox/旋转；后置复核失败保留实际字节并诚实告警。

## 验证

- 引擎 source-text-move.test.ts，最终5通过0失败；日志/tmp/pdf-move-text-engine-geometry.log。四旋转、原文字自身倾斜、多对象跨页及控制文字/字体/几何保留，输入拒绝零写入，写后复核故障保留实际平移文件。已登记package.json默认test命令。
- 前端6文件53通过0失败，/tmp/pdf-move-text-front-reviewed.log；包括绑定/零位移重置、旧控件/权限/草稿变化、刷新故障保留、公共入口的原对象ID、实际预览data状态及独占隔离。
- native.py文字开关三个现有入口集合增加moveText，native_pdf_contract将其纳入现有确认/回执种类；没有新增签发函数或步骤。服务 test_native_pdf_move_text_service.py 初始4通过（preview/preview_file/save开关关闭拒绝及实际保存）；最终页面几何复核加强后，仅实际保存参数1通过3未运行，/tmp/pdf-move-text-service-final.log。未确认时不预留修订；确认后登记修订、验收仍false但实际下载可用。下载字节等于预览；pypdf基线差[20,-30]、控制文字保留、来源字节不变。使用现有内存fixture仓储，不是生产身份HTTP验收。

## 实际浏览器和独立回读

smoke/pdf-move-text-smoke.mjs最终目录/tmp/pdf-move-text-browser-final2，日志/tmp/pdf-move-text-browser-final2.log。真实源码pdf-main、PDF.js和实际CLI模型；输入未暂存时prepareSave拒绝；公共入口暂存[40,-40]，插入入口禁用，Undo/Redo、重载恢复、390×700输入截图、真实CLI实际PDF预览均通过。不是只验证“请核对预览”提示；必须data-pdf-preview=true并实际读取preview-file。

actual-preview.png及move-narrow.png均已目视；执行清单为“移动原文”1项、0告警且确认框初始未选，实际纸面显示移动后的原文字。独立pypdf：Original preserved从[40,450]变为[80,410]，/Helvetica和12pt保持；原来源SHA不变。浏览器pageerror和HTTP>=400为空。

最后仅补输出几何复核，不改writer；最终bundle以同一请求重算，final-runtime-continuity.json确认与moved.pdf逐字节相同，最终PDF SHA256=4d926132d5b1d2a14fd0664814ff8be98cfbda4f9c15f49a27251a048f941dd6，bundle SHA256=ec98caeb9bb885b083b391737a5c9473c50cfd31f6f4bfd8c939a044eeee1647。不冒称最终bundle在浏览器重新完整执行过。

首次浏览器发现实际预览早退漏项；/tmp/pdf-move-text-browser.log和新增宿主preview-red.log保留RED后才修复。第二次final.log失败是烟测等待草稿长度而未等待异步控件更新，修为等待同一disabled条件后final2通过；未放宽禁用断言。Vite仍提示其它格式的fast-xml-parser/saxes/utif2预扫描解析问题，未隐藏。全局tsc最终退出2且与上一批日志逐字节相同（632条既有诊断）；不声明全局类型检查/生产构建通过。git diff --check、烟测语法和修改Python语法检查通过。

## 剩余范围

本批是整文字对象平移，未完成任意多对象段落块编辑、自动reflow、跨对象游标/选区、画布直接拖动、AI move_text_block工具、复杂源及任意操作组合。浏览器是Vite源码/烟测API适配器的实际预览，服务保存下载是独立fixture，不混称同一条生产浏览器授权保存链。未提交/部署/开启功能开关；穷尽PDF缺口目标仍active。
