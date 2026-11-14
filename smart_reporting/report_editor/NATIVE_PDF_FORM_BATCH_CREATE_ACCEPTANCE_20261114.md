# PDF 多字段同批创建验收（2026-11-14）

纯createFormField草稿支持多个独立字段统一预览/保存，保留原500项预算。后端先校验全部配置、原SHA/页/矩形及新旧名称/父子前缀冲突，再复用既有单字段writer，服务端按原页序重绑中间SHA（含radio跨页Widgets）。回执和确认摘要绑定全原批次和实际最终字节；后段失败保留前段产物并返回原索引告警。没有新路由或签发步骤。

前端支持Ctrl连续放置，按唯一字段名绑定本批画布条目；属性、拖动、方向键、删除和取消只修改选定的新字段，不清空其他字段；radio取消按整组处理。可撤销/恢复草稿，创建入口仅对纯创建草稿开放，其余设计操作保留各自隔离边界。

## 验证

- /tmp/pdf-form-batch-engine-radio.log：8通过0失败（4批创建、4原单字段），实际PDF字段树、值、页面/正文、源SHA、原索引/摘要及独立radio跨页映射。错误后段配置/来源/命名/落点在任何save前拒绝；后段writer失败保留首字段字节与索引[1,2]告警。故障探针曾过早在首字段写后复核触发，失败日志engine-green保留，后续定位到第2次及以后save。
- /tmp/pdf-form-batch-front-final.log：6文件117通过0失败。涵盖批追加、精确替换/删除、字段名/来源/范围、Ctrl连续创建、属性/键盘几何、来源/手势变化和实际公共创建入口；React act警告保留，不冒称日志无警告。
- /tmp/pdf-form-batch-service.log：1通过。实际NativeEditorService、隔离CLI、未确认不登记修订、预览确认/保存/下载流；下载等于预览，pypdf和模型回读确认层级text/checkbox字段及所在原页，原正文/页数/源文件保留。pdf_text_enabled=False证明沿既有表单能力而非绕过文字开关。使用内存fixture仓储，不是生产HTTP授权浏览器保存。
- 独立审查无重要发现。全局类型检查/tmp/pdf-form-batch-types.log与上一批最终日志逐字节相同（632条既有诊断），无本批PDF诊断；仍退出2，不声明全局构建通过。

## 真实浏览器

smoke/pdf-form-batch-create-smoke.mjs实际源码宿主、真实FormDesignLayer/PDF.js和隔离CLI；产物/tmp/pdf-form-batch-browser，日志/tmp/pdf-form-batch-browser.log。Ctrl第一字段后保持工具，完成属性卡后无需再次点工具即可创建第二字段；分别改Field2必填/值，追加勾选Field3；方向键只移Field2，删除Field2保留[Field1,Field3]，Undo恢复3字段，页面重载草稿恢复；实际PDF预览applied=[0,1,2]、skipped=[]。

独立pypdf确认Field1/Field2/Field3、Field2=Second field且必填、Field3=/Yes、3个Widget均有AP、原正文保留；源PDF SHA不变。fields-narrow.png及actual-preview.png已目视；390px下属性卡left62/right282/clientWidth=scrollWidth=218，无横向溢出。pageerror和HTTP>=400为空。Vite仍有其它格式fast-xml-parser/saxes/utif2依赖预扫描提示，未隐藏。

隔离CLI在/tmp/pdf-form-batch-runtime/dist/cli.mjs，复用已安装依赖，不是自包含发布包；不写shared static/dist。脚本语法和git diff --check通过；未提交、部署或开启生产开关。

## 剩余范围

本批只完成多字段创建及独立画布管理，是复制/重复/粘贴的基础；源字段复制、系统或文档剪贴板、快捷键及跨文档粘贴尚未交付。既有复杂多Widget/XFA/签名保护来源限制保留。多次复用writer会重复解析，大批量性能未验收。浏览器是Vite源码和烟测API实际预览，服务保存为独立fixture，不混称完整生产浏览器保存链。整体穷尽PDF缺口目标仍active。
