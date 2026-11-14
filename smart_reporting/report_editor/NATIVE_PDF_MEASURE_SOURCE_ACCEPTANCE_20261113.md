# PDF 完整测量标定组件验收（2026-11-13）

固定 GenOffice ref：f8c17004fb730df11f0f743164ffd8b4281bb38c。源 MeasureScaleDialog SHA256：be621bc5ec0240aee2ab5d1eb4413007f10348f1abfd6e6c220d97919bd86494；本地 03167fb20af0638f82e3964fc50ddfa0ffa61fab298661c0e6bcbd62f58caadc。Apache-2.0，沿用 LICENSE/NOTICE。

完整保留参考线长度、单位、默认 m、12 字符限制、非法输入提示及确定/取消；适配顶层原生 dialog、中文、键盘/IME、焦点恢复、小高度滚动和固定操作区。确认使用既有 pdfMeasurementOperation 和原生 Line writer。比例仅会话有效，各线保存独立长度标签。取消重新标定保留旧比例；来源/页/草稿变化或只读状态拒绝迟到提交。异步错误保留输入，已经提交后的刷新失败不会重复提交。

证据根：/home/junge/codex-evidence/smart_reporting/office-image-links-measure-20261113/pdf。源 UI 3 项、host 8 项、既有受影响宿主 1 项均有定向日志；independent-review.md 为独立只读审查。未重复完整测试。

正式 browser-final-v3 唯一运行 exit0：1440×900、640×320、390×320 下实际逐控件焦点和点击命中；非法/非 ASCII 单位错误、Escape 取消、两页 UserUnit 2/1 的真实五条线、重新标定、Undo/Redo、预览、保存、下载和修订 5 重开均完成。68 个实际 HTTP JS/CSS 资源 SHA 匹配冻结 static；page/console/HTTP/asset errors 均为空。

实际 PDF 4355 bytes，SHA256 4a74492fb42af6c3c4da2dd6da1e5e09f444eab7e49d73f93acd0852e56183da。独立 pypdf 读取原生 Line/AP 的五个标签为 2.00/1.00/2.00/2.00/4.00 m；页面 CropBox、MediaBox、UserUnit 和原正文保持。validation.ok=false，返回具体待复核原因并照常签发已生成 PDF 下载链接，未伪标验收通过。

冻结源码 final-source-v3 清单 SHA：5f915fbb9fd59ea46d19b980a43ccf120d7c42e199b46696a67665a227ad6e1d；Vite manifest SHA：5658c601dbbba3447288e85c0da97914e99778719232d14c6ff1ce1f1bf01aa4；725 个静态文件身份清单 SHA：0ecca13bbbc664cdbdd81a49658c48f0b8c9c20421d92ed7528eb57a4a1b8a74。构建 45.54 秒，原预算通过；XLSX 主包经本轮独立组件拆分为 248.6 KiB，未提高预算。

pdf-runtime-final-v1 的 CLI SHA：e7d3f10aa28c38c9824ee24eda78e4ef1bcc95ce9e31e81235160279851667c1；256 个源码输入和 713 个依赖输入登记，v3 源码逐项兼容，PDFium/HarfBuzz WASM 单独登记。本轮核验入口配置与当前身份，不冒称历史每次文件打开跟踪。

早期 browser-stage-v1 的 304 缓存判定错误保留 failure.json，事后只读复核与正式 v3 运行分别存档。真实服务/授权/CSRF/引擎/下载链使用限定内存夹具，不冒称生产数据库、部署或四格式全部组件完成。共享 static/dist 未覆盖。
