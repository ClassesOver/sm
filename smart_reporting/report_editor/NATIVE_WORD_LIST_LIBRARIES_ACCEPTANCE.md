# Word 普通符号／编号库与自定义定义验收（2026-11-13）

## 范围与来源

固定参照 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。复用现有原字节 `list-presets`、`DefineBulletDialog`、`DefineNumberFormatDialog` 和编号格式化，不改 vendor 以修宿主行为。`docx-list-gallery.tsx` 扩展三种图库，Home/Ribbon 在原符号和编号分裂按钮接入；默认多级图库保留。六套符号、八套编号、最近／文档／级别区、清除与完整符号／编号定义进入既有 `applyDocxCustomList`、`setParagraphCustomList`、草稿和历史协议。

范围限可信原有顶层段落，包含多段同事务和应用时来源复检。图片项目符号明确禁用并说明上传与编号资源写回未接；独立“设置编号值”的 continue/restart 对话框、复杂嵌套目标、完整段落选项仍开放。自定义定义的 start 字段不等于独立设置编号值功能完成。

## 定向回归与真实浏览器缺陷

证据根 `/dev/shm/office-word-list-libraries-20261113`：

- `gallery-red.log` 六项失败后，`gallery-green.log` 新六项加既有九项，共15项通过。
- `integration-red.log` 真实 Ribbon 两项失败后，`integration-final-green.log` 新两项加既有39项，共41项通过，验证同事务多段、Undo/Redo和过期来源拒绝。
- `integration-overlapped-probe.log` 是写入重叠导致的通过探针，不作为RED证据。之后只临时移除本批两个控件props取得独立RED，恢复后GREEN。
- 真实 Chromium 发现源 Dropdown 被包在 label 内，选 Arial 后默认激活 trigger 再次打开菜单，遮挡确认。捕获阶段只对 label 内 `.gs-dd-item` 取消默认动作，保留 React 选中和传播。`dropdown-label-browser-red/summary.json` 记录 expanded=true 及第二次 trigger click；最终 `dropdown-label-browser-green2/summary.json` 三种图库均 expanded=false，可确认。中间名为 green 的目录实际失败，原样保留。JSDOM基线原已通过，不能冒称复现了真实浏览器缺陷。

## 冻结版本完整 HTTP 链

物理产品源码快照 `/dev/shm/office-four-format-source-library-20261113/source`，静态目录同根 `static`；manifest SHA256 `845d993207be6b2d6eeae28cf0b5abab8c1aaded0b9a9e60e7ca86a890a4d56c`。DOC bridge SHA256 `090f56b017283affaa08596d84fcb10794fb8bf9e9a6e50ca3f51f0244a4fcd1`。

`browser-frozen-01.log` 退出0，`browser-frozen-01/evidence.json` 保存完整结果。真实操作覆盖两段普通符号库、撤销重做、清除、第一段自定义 ★／Arial、第二段 Roman 库及自定义 `第%1项`／start7／Arial14／123ABC／粗斜体／右对齐、390px两种对话框、reload草稿恢复、4→5修订保存、点击授权下载及明确新修订重开；API回读与下载同SHA。151个实际HTTP JS/CSS资源逐字节匹配冻结磁盘，page/console/HTTP/asset errors均为空。

独立 lxml/python-docx/ZIP 检查确认两份不同 numId 的九级定义、upperRoman、start7和全部样式字段，保留首段居中／粗体、全部原文、旧段落、旧编号定义与其余15个包部件。实际下载38307字节，SHA256 `3a58ed202e9a9c081bf4dd88afef8cf874449e51d282caa17b2f86e10f1bf02c`。root再次独立核对151资源、下载身份及ZIP定义，记录在统一目录 `root-word-xlsx-asset-download-verification.json`。

root目视冻结的 `symbol-mobile.png`、`number-mobile.png`、`reopened.png`：390px宽内字段和确认按钮可达，无横向裁切；重开显示星形符号和蓝色粗斜 Roman 编号，原标题／编号仍在。此处不承诺桌面Word版式等价、所有字体或所有目标验收。

保存仍返回 `validation.ok=false`，原因 `native_source_review_pending`，不将其标成业务验收通过；实际身份已核验的文件正常签发下载。

## 分层失败记录与边界

源码开发夹具01–04均保留。02发现窄屏裁切并修CSS；03发现上述label默认激活问题；04完整UI／保存／下载／重开与独立文件检查通过，但末端24次开发夹具字体URL 404使脚本退出失败，不能称完整通过。之后仅测试工具补字体资产symlink；本次冻结生产包完整链无404且退出0。该后补测试脚本身份与物理源码快照有意不同，产品五文件及Python保存适配身份保持一致。

本批统一完整前端类型检查退出0，Vite45.97秒，400个JS原预算失败项为空，四桥构建通过；未提高预算，未重复完整测试，未覆盖共享static/dist，未提交、推送或部署。四格式总体对齐目标仍active，不能由本专项推定全部列表族或全部Word完成。
