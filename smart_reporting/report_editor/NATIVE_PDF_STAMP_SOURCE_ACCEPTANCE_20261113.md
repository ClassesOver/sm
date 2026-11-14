# PDF 水印与页眉页脚完整组件（2026-11-13）

## 范围与实现

固定 GenOffice ref f8c17004fb730df11f0f743164ffd8b4281bb38c 的完整 StampDialog：水印/页眉页脚双页签，文字、角度、不透明度、字号、共享色板、实时预览、六个页眉页脚区域、页码占位符和起始页。增加现有草稿配置重开、仅清除水印操作、取消和异步来源保护；不是重新实现 PDF writer。

宿主 src/pdf-stamp-dialog.ts / pdf-stamp-dialog-source.ts / pdf-stamp-dialog.css，原生保存继续使用 buildPdfStampsOperation 与既有 setStamps。来源摘要及本地适配详见 vendor/genoffice-pdf/SOURCE.md 和持久证据 pdf/stamp-provenance.json。

## 已有定向证据

持久根：/home/junge/codex-evidence/smart_reporting/office-component-inventory-20261113/pdf。

- host 6 项：取消、迟到加载、过期草稿/权限/销毁、仅清除 setStamps 保留其它操作。完整源 UI 3 项：双页签/初始状态/实时预览、色板 Escape 和焦点、内联错误/IME；新增标签与焦点修正各有定向回归，不能重复计入总数。
- browser-stage-v1 暴露 640×360 色块被粘性底栏覆盖，增加 scroll-padding / scroll-margin；v2 暴露角度滑块标签混入动态数字，补明确 aria-label。失败证据保留。
- browser-stage-v3：1440×900、640×360、390×320，初始与恢复两轮双页签共12项布局/真实焦点与命中检查；取消/色板 Escape/UndoRedo/刷新恢复/清除/实际预览/保存/下载/新修订重开通过，71个实际 HTTP JS/CSS 与构建文件摘要一致，无浏览器错误。
- 测试使用真实授权/CSRF/API/PDF引擎/签发/下载和隔离内存修订仓储，不等于生产环境或真实 AI 验收。
- 独立 pypdf / Pillow 核验实际下载的三页：正文文字和内容运算符保持、仅第一页旋转90°、每页三个实际图像与请求 PNG 可见像素及 alpha 完全一致、实际 ExtGState 不透明度0.45、逐页页脚不同。下载179635字节，SHA256 a17efdc6e450c65bb351dab33175bdaea96df967f05aa5a18447567729d7beb3。
- 保存 validation.ok=false 且明确 native_source_review_pending，仍正常签发下载并重开；没有伪报业务验收通过。

## 状态界限

该证据来自 PDF 独立 source-stage，构建 manifest e417f6e2e27387aa2764fd29622e8dc12e0402bdf7a003e9e92403c000981747。本轮四格式最终源码冻结、原预算和统一构建验收尚待 root 完成。PDF全组件、签名、AI及其它未知项不因本组件通过而标完成。

## 最终冻结验收

统一 final-source-v2 4439文件，源码清单 SHA256 6d89e82804f0535f999491b487ab192608a6fe1b5cb75674bf71c299c8eb438e。tsc --noEmit、Vite（44.94秒）和未调整的构建预算均exit0；静态720文件，manifest SHA256 c2d8c235b8ac55347f2cad2d0af09d65a167776c3659f7c98bbb2da48076e203。

旧PDF bundle虽然PDF代码未改，但metafile含PPTX/index和XLSX/chart-read输入，逐项比对发现两项不匹配，故拒绝复用并显式重建。pdf/runtime-final-v2实读969输入，其中256个物理冻结产品输入，全部匹配清单，无工作区源码逃逸；CLI SHA256 83b2be487265da1f09184e2810f03b3705368a76eb3cdc780519e6ebff050151。

browser-final-v2正式12布局检查、71实际HTTP资源、1save/download/新修订reopen、0errors通过。独立pypdf/Pillow回读同样通过。实际下载179635字节，SHA256 b04500a9a23421151f846d8700f45f830ce643d537550591a99c1ea1e6031b80。validation.ok=false具体原因保持，下载正常签发。完整证据见pdf/browser-final-v2/evidence.json和independent-file-check.json；测试宿主300个Python快照文件与工作区实读一致。

独立agent只读复核进一步确认71资源、实际Do图像/CTM/alpha和969构建输入身份，并补登记runtime两项WASM SHA（wasm-identities.json）。执行证据边界：正式launcher显式配置runtime-final-v2，当前只读bridge_execution可解析同一CLI/SHA，但现有HTTP证据没有逐调用entry路径/SHA回执，也未快照历史继承的WASM_DIR/NODE_PATH；不能声称已用文件open trace证明历史每次WASM加载。Python宿主仍使用现有包/venv（300个已冻结Python输入实读匹配），不称完全独立部署。详见independent-review-docx-agent.json、engine-entry-trace-review.json。
