# PDF 对齐并行批次验收

2026-11-11。固定来源 f8c17004fb730df11f0f743164ffd8b4281bb38c。
本批覆盖页面提取、裁切控制柄、安全单 Widget 删除，不代表完整 PDF 对齐或生产部署通过。

- 页面提取：保留页序、绑定父修订身份、独立登记/下载/重开，来源和草稿不变；暂拒绝表单、批注和保护来源，书签/附件不复制。登记或验收失败保留身份可读的下载，超过在线编辑大小限制也保留下载。
- 裁切：实际页面画布、八方向控制柄、区域移动及数值联动，复用原有逆视口坐标和撤销。
- Form Design：严格来源/字段/Widget 身份绑定的安全单控件删除；保留幸存字段和批注引用顺序。仅允许单操作保存，复杂字段和其他设计命令仍未开放。

## 验证

页面提取 bridge 3 项、真实 Python 引擎 5 项通过；前端提取 10 项通过。裁切及表单引擎/界面专项结果详见各自验收记录。

必须保持的非阻断契约日志 /tmp/pdf-parallel-required-contracts-20261111.log：75 passed、2 deselected。随后仅补默认排除的两个集成参数，/tmp/pdf-parallel-required-integration-20261111.log：1 passed、1 skipped。原测试跳过理由为“原故障契约已覆盖；此新增场景只核验真实CodeMode续改”，没有修改跳过规则。

页面提取真实浏览器 /tmp/pdf-extract-built-20261111-final-02/summary.json：ok=true，真实鉴权/CSRF/发布/下载和新 grant 重开；仓储为作用域内存 fixture。独立 pypdf 确认页序 three、one，来源 SHA/草稿不变；22 个加载 JS 与磁盘 SHA 匹配，无 console/page/HTTP 错误。manifest SHA256 为 6fbdb541ca7e617bff0f7a3cb6891ccb039699b6d63178a482cc11384e43c918。

Vite、budget 和 PDF 定向 TypeScript 编译通过，PDF bridge 已重新 bundle。统一 pnpm run build 的 tsc 被其他 XLSX 工作树 workbook-print-header-footer.test.ts 类型错误阻断，不能标记全项目构建通过。日志 /tmp/pdf-parallel-frontend-build-20261111.log、/tmp/pdf-parallel-vite-build-20261111.log、/tmp/pdf-parallel-tsc-20261111.log。没有运行全项目完整测试、提交或部署。

最后验收阶段根分区 100%、可用空间 0，沙箱启动报 No space left on device。裁切首轮 0°页拖动应用成功，90°页拖动被滚动取消；仅修 smoke 同步后重跑被 ENOSPC 阻断，原因尚未证实。表单浏览器只完成 grant/context/JS 加载，磁盘再次耗尽后页面崩溃，未触发删除。两项浏览器均未通过，详见各自专项文档，不能用页面提取结果代替。

## 尚未完成

OCR、完整静态文字编辑（首批单行插入补齐见下）、既有图像编辑、复杂表单/批注、多文件页面操作、转换、密码与证书签名、完整真实 provider AI 和生产宿主验收。细分见 NATIVE_PDF_ALIGNMENT_STATUS.md。


## 继续验收最终结果（同日）

磁盘恢复后继续，最终两项浏览器均通过；上文磁盘失败与早期 RED 作为历史保留。

- 裁切：/tmp/pdf-crop-handles-final-resume03 证明背景 pdf-document-pages 平滑滚动发生时，画布位置/尺寸与活动页未变，却被全局 scroll 监听取消拖动。最小修复为画布实际位置或尺寸变化时才取消；保留 wheel/blur/resize 等守卫。新增/受影响定向回归 4 项通过，其余 18 项未重复运行。最终 /tmp/pdf-crop-handles-final-resume04/summary.json 为 ok=true，四旋转均拖到 10%/20%，背景 39 次滚动仍发生但不再误取消；窄视口、保存下载与独立 pypdf 四页 CropBox/正文/MediaBox/Rotate/UserUnit=2/表单值检查通过，22 个实际加载 JS SHA 匹配，errors=[]。认证/修订/保存 HTTP 是明确替身，实际 PDF.js/引擎/下载字节真实；纯裁切实际预览和生产鉴权不由本结果证明。
- 表单删除：final07 真实浏览器 RED 复现遗漏 removeFormWidget 实际预览白名单，导致只校验 JSON、未加载 PDF；新增宿主测试先 RED 后 GREEN（1 项，其余 2 项未重复）。四处最小前端接线补齐实际预览、确认面板、保存准备及中文标签。最终 /tmp/pdf-form-design-browser-20261111-final08/summary.json 为 ok=true，真实 grant/cookie/CSRF/引擎/发布/下载和授权重开通过，仓储是作用域内存 fixture，无 HTTP 或 PDF 替身。独立 pypdf 确认只剩 keep 字段、单个有效 Widget，正文及来源 SHA 不变。22 个实际加载 JS SHA 匹配，page/console/HTTP 错误均为空。确认属于 UI 核对；服务端 removeFormWidget 仍以来源/字段/Widget 身份验证为依据，尚不强制确认摘要，不冒称与 replaceText 后台强制摘要协议相同。

两项最终 manifest SHA256 均为 0a7bb15fd8019797b68833ba6d60d20beb0355163224ee0ebfa27e042bb4c1b8；实际 PDF chunk 为 lazy-pdf-main-DHCSOcAX.js。root 独立读取 summary 并目视表单 preview 和裁切 270°截图，专项负责人另已逐张检查全部截图。

继续阶段 PDF 定向 TypeScript 编译通过，Vite 45.02 秒打包通过，budget 与 budget contract 通过。完整 tsc 曾在继续初轮通过，但后续其他会话新增 docx-hf-probe-scope.ts / slides-arrange.test.ts 类型错误，当前完整 pnpm run build 仍未通过；准确日志 /tmp/pdf-parallel-resume-build-20261111.log。独立成功日志 /tmp/pdf-parallel-resume-vite-20261111.log、/tmp/pdf-parallel-resume-pdf-tsc-20261111.log。没有重复完整测试或再次运行未受影响的 76 项发布回归；后台发布链未变。未提交或部署。

## 静态文字与裁切实际预览（同日后续批次）

- 单行静态文字首批已交付：配置字号/颜色/左对齐后点击来源基线，写入可检索 PDF 文字对象，单操作保存并强制匹配实际预览确认摘要。复杂来源、字体选择/多行/其他对齐及混合编辑仍未开放。输出复核失败保留实际生成字节并返回告警；新增 HTTP 故障注入证明 validation=false 仍签发正确身份下载。详见 NATIVE_PDF_STATIC_TEXT_ACCEPTANCE.md。
- 纯 cropPage 草稿已加载真实写回 PDF 预览。四旋转非零 CropBox/UserUnit=2 的实际 viewport 尺寸、返回原稿草稿不变、最终保存字节与预览一致均通过；裁切仍为隐藏内容。详见 NATIVE_PDF_CROP_HANDLES_ACCEPTANCE.md 的后续章节。

最终浏览器目录 `/tmp/pdf-static-text-browser-20261111-final01` 与 `/tmp/pdf-crop-handles-final-preview01` 均 ok=true，manifest SHA256 均 `000be7f5abfd4d62859a6786cd6525349a30f1cfe3b61744ffc82d74de9302ae`，无 JS/console/HTTP 错误。文字使用真实 grant/cookie/CSRF/发布/下载/重开，仓储为作用域内存 fixture；裁切 HTTP 认证/修订/保存是明确替身，实际 PDF.js/引擎/字节真实。两者证据边界不能互相替代。

本批引擎7项、前端文字专项24项通过；最后受影响宿主及裁切对话框14项通过（与前者重叠，不累计）。后台服务及必须保持的非阻断合同78 passed、2 deselected；最终告警措辞回归仅重跑受影响HTTP故障1项通过，未重复全量。PDF TypeScript、Vite、桥接bundle和budget contract通过；完整项目tsc仍被其他会话的Word/XLSX类型错误阻断，本轮首次构建workbook-main 251.8 KiB超过250 KiB预算，未放宽预算。未提交、未部署、未打开生产功能开关，不代表完整PDF对齐通过。


## 共享构建变化后的补验

首轮验收完成后，其他会话重建了共享 static 目录。因资源身份变化而补验，并非无变更重复完整测试。文字 `/tmp/pdf-static-text-browser-20261111-final02/summary.json`、裁切 `/tmp/pdf-crop-handles-final-preview02/summary.json` 均 ok=true；实际加载资源匹配且运行期间 manifest 稳定，SHA256 为 `6a34663ff0c246aec181d1aa7dfb985be956a6e33d7a8c3d79af476a4595c9de`。两项沿用原先明确的真实服务/替身边界，错误列表均为空；独立 pypdf、实际预览、下载和文字重开检查再次通过。root 读取两份 summary 并目视最新文字重开截图。只读独立复核未发现新增严重问题。
