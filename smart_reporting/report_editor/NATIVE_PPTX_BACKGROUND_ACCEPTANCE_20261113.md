# PPTX 完整背景格式族专项验收（2026-11-13）

## 范围与固定源

固定源 /home/junge/pros/genoffice-source-full，HEAD f8c17004fb730df11f0f743164ffd8b4281bb38c。迁移 FormatBackgroundPane.tsx 完整三模式与操作族：纯色 ColorWell/共享图库、双端渐变与0/90/45/径向、图片预览/选图/拉伸/平铺、独立隐藏背景图形、当前填充应用全部、恢复版式/母版背景、折叠。宿主复用已迁 SlidesFormatColorWell 的图库、原生颜色输入、Portal与焦点规则；源中文和样式限定本族。

既有图片模式和应用全部提交来源页+实际媒体SHA/size；服务端从当前PPTX解析受控mediaRef，不接受客户端路径，不新增媒体。上传图片仍走既有bounded bytes journal。纯色改走规范setBackground，同步全幅无字底板。新增journal进入NativeDraft恢复、单笔历史、Undo/Redo、真实render-tree与保存。

未迁移自定义放映：固定源仅localStorage会话列表，无实际PPTX custShow writer/reader；不得以会话列表冒充持久化完成。无纹理库、多色标、任意角度源UI，不据旧泛化文档虚列缺失。

## 定向验证

- bridge新增与受影响背景7/7，Python新增复用校验7/7。
- UI：pane5、兼容dialog8、main8，共21个独立用例分轮定向通过；未重复完整测试。包括四方向、save flush、切页丢弃、迟到pick/decode（关闭/切页/保存/销毁/外部草稿变化）、Escape恢复焦点。
- 既有图片弹窗保留backgroundImage兼容入口；formatBackground使用完整实时窗格。
- 产品源码稳定SHA：证据目录product-source-ready-identities.json。未改共享vite配置、static、engine dist；统一tsc/build/freeze由root执行。

## 源码真实浏览器v4

证据根 /home/junge/codex-evidence/smart_reporting/office-next-source-families-20261113/pptx，browser/v4/evidence.json。

- 1440×900原图平铺/应用全部、Undo/Redo、独立graphics；真实canvas截图变化。
- 纯色源图库 #E97132、径向渐变与resetUndo；640×360滚动、色板方向键、Escape恢复触发器焦点。
- 刷新恢复原journal；唯一一次保存、唯一一次下载；实际HTTP125资源，错误0。
- 原文件SHA 8d3eb4a04d751f1207e38ba7dcafc37c712d75a331114bab1fd96606608bb320 不变。
- 下载SHA c3a9c865845b0ce4c6372ac91ef97df4a2f2d459fe6a0760b675963d3f444765，50,343 bytes。
- ZIP/lxml及python-pptx独立回读；仅ppt/slides/slide1.xml、slide2.xml、slide3.xml改变，图片媒体字节、正文和讲稿保留。
- 将同一下载文件作为新来源独立重开，真实render-tree及图片平铺/纯色/径向回读通过；重开0额外保存/下载，新来源SHA等于下载SHA。
- 授权、组织/用户/任务作用域与修订注册是显式native夹具；writer/reader/render-tree/下载均实际实现，不冒称生产授权或正式持久化验收。独立重开夹具UI修订号重置为1，验证的是revision-2下载bytes，不据UI号码宣称生产修订注册。

## 失败记录与修复边界

v1低高度对象检查器被旧布局裁切，0保存/下载；增加本族小屏停靠。v2在CSS写入前加载旧HTTP样式（failure.html可核），仍0保存/下载。v3窗格可见，Portal Escape被本族React冒泡守卫拦截，已限定DOM自身守卫并加定向回归，0保存/下载。v4完整成功，不覆盖失败证据。第一次bridge GREEN失败为测试把页先改成图片后再当非图片验证，已将拒绝检查移到修改前；RED与日志保留。

## 正式冻结包

正式统一source-v2 scope manifestSHA fc493bcb2305db74aac56653de4fc5ffc1fd7ba4f41fad5ecabdb705fd05b872；静态资源manifestSHA 7949df1457ac33345c20d4ba447bc26d0a922881f8812040838bf82d6f00e0a8。root执行tsc、Vite（45.32秒）及原budget均exit0。先前source-v1 manifest仅为历史，不用于正式复验。

正式证据 browser/frozen-v1/evidence.json，runner身份 frozen-runner-identities.json；smoke runnerSHA 990bbdd641a3a17ea015f87dde712e5883e350713f6600e0bdbdefe737791fcc。隔离引擎279个输入与source-v2逐项SHA一致，0缺失/0漂移；Python包装层与统一backend-wrapper-identities一致。

- 四组完整浏览器交互通过，包含640×360滚动、方向键/Escape焦点和刷新草稿恢复。
- 151个实际HTTP资源逐项与冻结static文件SHA一致，errors=[]。
- 全新夹具仅1次save、1次download，原文件SHA保持不变。
- 下载SHA 2a049615b34bb23d29bbca6c77984df91c02eeb475434ccdd94af276a3c4110a，50,343 bytes。
- ZIP/lxml与python-pptx独立回读通过；仅slide1/2/3.xml变化，媒体字节/正文/讲稿保留。与源码v4下载的ZIP逐项payload完全相同（ZIP容器时间戳造成整体SHA不同）。
- 同一下载文件独立reopen actualRenderTree=true，平铺图片/纯色/径向回读与截图通过；额外save/download均0，reopen来源SHA等于正式下载SHA。
- 保存下载与独立重开均为显式fixture授权/修订宿主，不冒称生产授权或生产数据库持久化。未提交、推送或部署。
