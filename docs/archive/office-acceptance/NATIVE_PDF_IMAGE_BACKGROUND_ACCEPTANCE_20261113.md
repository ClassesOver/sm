# PDF 已有图像缩略图真实背景补齐（2026-11-13）

## 范围与原始失败

固定参照为 GenOffice `f8c17004fb730df11f0f743164ffd8b4281bb38c`。本批只补单目标 `transformExistingImage` 的待处理缩略图：先在内存 PDF 副本移除已核验的原图，渲染保留底色和正文的局部背景，再叠加前景图像。没有新增主画布即时预览、多目标操作或新的保存、发布、下载协议。

证据根：`/home/junge/codex-evidence/smart_reporting/office-image-background-20261113`。

`alpha0-red/` 保留旧构建上的真实失败：来源 `27fc4202a33266861338fd2066cdde1372d0ff9a041b2618407a109e32bba079`，480×360 前景的 172800 个 Alpha 均为 0，但合成后原图中央 25 个样本仍有颜色。该记录保持 `ok:false`，没有把它改写成通过。

## 产品合同

- 新只读 `POST /api/image-background` 和 CLI `imageBackground` 按 source/page/image/expectedImageSha256 唯一定位已授权目标，不接受路径或客户端 oldRect 作为对象身份。
- display-space clip 为四个有限数值，须在实际显示页内；前端 oldBox 四边扩 2pt 后夹到 viewport。前端按长边 720 推导请求宽度；后端宽高各不超过 2400。高度统一为 `max(1, round(clip.height * pxWidth / clip.width))`，避免半像素边界的跨语言运算顺序差异。
- 回执核对四身份、clip、PNG SHA 和实际尺寸。背景和前景均验证并解码完成后一次挂载；背景为普通混合 z3 同级层，前景保留既有 belowText z4/multiply 或 aboveText z7。
- 两路请求共享取消信号；撤销、来源/操作/渲染换代和销毁后不能挂载过期结果。实际 PDF 预览使用渲染后的文件，不重复挂待处理图层。
- 替换图像仍读取背景，但无需读取旧图像像素。只读接口不创建修订、不改来源文件。

## 定向验证

| 验证 | 结果与明确范围 |
| --- | --- |
| Python 回执与路由边界 | `python-background-green.log`：20 项通过；包括身份、clip、PNG、cookie、CSRF、来源变化和禁用状态。引擎回执部分使用 mock，不能代替真实渲染。 |
| 取整及 imagePixels 邻接 | `python-background-round-and-adjacent-green.log`：14 项通过、33 项未运行；包括新增半像素边界及已有像素读取回执检查。 |
| 真实 HTTP 到 CLI | `python-background-actual-http.log`：1 项通过、21 项未运行。实际授权会话、工作区读取、Python wrapper 和隔离 CLI 返回底色及黑字；错误 digest 返回 422；文件字节与修订数不变。 |
| 前端 | `frontend/frontend-targeted-green.log`：24 项通过，覆盖 API、身份、严格 clip 四键、原子挂载、取消、缓存 ready 和 replacement 分支。RED 文件明确标为会话摘录。 |
| 后端引擎 | `engine/targeted-green.log` 原始日志仅包含后加的 2 项通过：四旋转非零局部 clip 与半像素取整。最初 4 项通过只保留了代理会话报告，原始日志未找到；不能把当前日志描述成 6 项完整重跑。RED 文件是观察摘要。 |

未运行完整测试套件，也没有为补记录重复保存或签发文件。日志中的 `imghdr`、Pillow 旧接口弃用警告保留。

## 受控构建与输入身份

受控父源码 manifest 为 `ecf58e3390702b75610cf6ddce2800d4e768d53d45545170f6dae0f85a95fd46`，保留另一线程已有的 workbook/DOCX 贡献，仅覆盖本批指定 13 个产品/测试文件。最终源码 manifest 为 `9a0a8d98c2daa8337d145c278fd4e21b63ea56efdcd383b54e99c537b909cbf9`。

- 最终 Vite 构建、`tsc --noEmit` 退出 0；1195 个实际源码输入、4889 个依赖输入、783 个输出逐项回读匹配。
- 最终静态 manifest：`68bcbe2012a08b1910ba557e2c78875dbb162631322e6aa33ede652757ffb422`。
- 原预算脚本 SHA `6345b193af6a742e48e3067ddebe7dfc36e2813130f8eeb68c94516ff3e9e9d2` 未变，原 assets 范围的 485 个 JS 分块无超限。一次过宽的递归扫描误把既有 PDF.js wasm fallback 计入普通分块，单独保留失败结果；没有放宽阈值。
- 首次候选构建后，独立校验发现 helper 又改为复用已解码节点。该候选完整保留于 `superseded-first-build/`，未跑浏览器；最终重新冻结两个变动文件后构建。相同文件仅在逐字节核对后硬链接去重。
- `controlled-source.tar.gz` SHA 为 `5858bf077cbcc48b7703fb32e47d24a863406a6d1594093f0415825177cc2d28`；独立解包读取核对全部 5598 个源码文件。归档不包含 node_modules 或 Python 环境，不代表整个 dirty 工作区或四格式所有功能通过。

实际后端 bundle 为 `cefb421c42d98f1bfcd0155dfc6d779aedccae98cb1523aa7b3b443e615fe6b6`。从 UI 受控父源码直接重建的另一候选不是该 bundle：两者 260 个非依赖输入仅 `pdf_engine/src/main/text-edit.ts` 不同。该实际输入另存 `engine/text-edit-actual-input.ts`，对照在 `engine/metafile-source-input-comparison.json`。root 又在原路径对 1015 个输入（260 源码、755 依赖）做构建前后 SHA 核验，并逐字节复建出实际执行的 bundle，见 `engine/verified-rebuild-inputs.json`。该事实不扩大 UI 冻结范围。

PDFium WASM SHA 为 `5e4cd023c3dad4a895b3571ca573d3fc51bac6de48360d95283134385b954eaa`。实际 bundle、两项 WASM、Python wrappers 另行归档；运行时仍使用外部 node_modules 链接，不宣称自包含运行包。旧批 `90cb...` runtime 未改。

## 浏览器和独立像素证据

两次窄浏览器运行使用同一最终静态资源及实际 CLI：白底来源为原始 `27fc...`，彩底来源为 `721841289ae83d676cb40eb73d21aaddd4a7d70c26e3dc620d4ef39a6bdba483`。彩底 fixture 用 pypdf/reportlab 在原图下方加矩形和短字；独立回读确认四页 0/90/180/270 旋转、非零 CropBox、原嵌入图字节保持。

- 白底前景 Alpha 全 0；root 从实际 thumbnail 截图独立读取目标 1530 像素，全部为白色。旧图残影已经消失。
- 彩底前景同样 Alpha 全 0；背景 PNG 有 19200 个非白像素及 280 个深色字像素。实际合成 screenshot 的目标 1530 像素均非白，其中 9 个深色字像素，1294 个主色像素为 `(38,173,209)`。root 已目视白底、彩底缩略图及原始背景 PNG。
- 两次各有 60 个实载 JS、16 个 CSS，SHA/大小与最终静态文件一致，page/console errors 为空。运行时 bundle、WASM、Python wrappers 前后重新采样并一致；彩底还重新采样了列明的核心输入。
- 窄运行包含移动、替换、延迟背景请求后撤销，以及实际预览隐藏待处理层；彩底明确检查背景和前景层均清零。替换单步旧像素读取增量为 0、背景请求增量为 1。

浏览器使用 Playwright route adapter 调用真实 Python wrapper/CLI，不冒充生产 HTTP 服务；实际 HTTP 另由上面的独立单项验证。白底 raw JSON 的 replacement 计数在后续操作后才计算，属于累计值，不能作为单步值；独立核验未采纳这两个字段。白底运行时没有可靠保存精确 harness SHA，不能以之后修改的脚本 hash 冒充；保留元数据勘误，不为此重跑成功操作。最终彩底脚本和浏览器结果单独归档。

`verify-browser.py` 的结果在 `independent-browser-readback.json`。另外，`verify-background-poppler.py` 用 pypdf 仅移除图像 XObject、保留矢量和正文，再用独立 Poppler 24.02 渲染四旋转参考。四个局部 clip 的 68182 个实色参考像素均匹配（每通道量化差不超过 1），文字包围框误差不超过 1px；不宣称不同渲染器的文字抗锯齿逐字节相同。首次参考器错误地把矢量矩形也删除，及首次脚本启动路径错误，均保留为验证器失败尝试，未改产品来迎合验证。

## 保留的边界

本批关闭已证实的单目标待处理缩略图原图残影；不代表主画布 live preview、全部 PDF 操作或四格式 GenOffice 对齐完成。保存、发布和非阻断下载没有新增写入路径，也没有本批保存/下载验收声明。全部 fixture 的 UserUnit 为 1，未扩展到任意复杂 PDF 场景。总目标保持进行中，下一候选仍是 XLSX Scatter 的 plot 级值标签和按轴 ID 的编辑等已盘点缺口。
