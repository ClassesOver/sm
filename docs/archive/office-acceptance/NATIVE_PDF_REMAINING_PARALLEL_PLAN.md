# PDF 剩余功能并行实施记录

2026-11-11。用户明确排除 OCR，授权其余缺口并行推进。固定 GenOffice 来源 f8c17004fb730df11f0f743164ffd8b4281bb38c。保留既有脏工作树，无提交、部署或生产开关授权。

## 分工与验证目标

- [x] 既有图像编辑：核对固定源真实图像对象能力，复用引擎实现来源身份绑定的最小编辑；验证原图像确实改变、正文/其他对象保留，不能用新增 Stamp 冒称完成。专属 existing-image 模块和测试由 pdf_crop_handles 负责，root 统一共享入口。
- [x] 表单设计：在已存在安全 Widget 删除基础上新增可验收的字段/控件创建或属性编辑；先 RED 后 GREEN，独立 pypdf 验证字段树、Widget、AP 和幸存结构。专属 form-create 模块由 pdf_form_design 负责。
- [x] 多文件页面操作：复用 fixed insert/replace 引擎，外部字节预算、双 SHA 来源绑定，禁止客户端任意 workspace 路径；通过现有 save 发布新修订。独立 pypdf 核对双来源页序/内容/盒子及父来源不变。专属 external-pages 模块由 pdf_extract_ui 负责。
- [x] 保护与转换：root 核对既有密码加密/转换能力和授权输出链路，选择已有固定引擎支持的最小真实交付；证书服务缺失不得伪造完成，所需依赖列明。密码不得写入草稿、localStorage、操作记录或日志。
- [x] root 集成：各自只编辑专属模块；root 负责 operations/CLI/native API/pdf-main 接线、来源哈希和统一构建，避免并行覆盖。仅运行受影响定向回归及必要非阻断发布合同，不重复完整测试。
- [x] 验收：冻结共享产物后进行浏览器真实交互、身份下载和独立回读；明确 HTTP/存储替身与生产宿主边界，再更新对齐状态。新签发步骤失败须登记 HTTP lineage，实际生成且身份可读的 PDF/Word 即使验收失败也继续签发，不标记验收通过。

## 当前状态

本轮六项计划已完成：真实图像对象移动/缩放、text/checkbox 新建与必填属性、外部页面插入/替换、AES-256 独立保护下载、PNG/JPEG ZIP 与本地 PDF→PPTX 已接线。三条真实浏览器链路及独立回读有证据；完整对齐仍未完成。复选框尚无同等浏览器链路，复杂字段、图片像素替换/剪裁、其他转换格式及证书依赖仍单列为开放差异。OCR 已排除。

## 最终验证与限制

- 批量交付浏览器：/tmp/pdf-delivery-batch-browser-20261111-root01/summary.json；manifest 5a02fa3eca66d4a4392813c5f6f5db287c77fd527ad6814019c475df2c4f7aa8。
- 表单 / 图像浏览器：/tmp/pdf-form-create-browser-20261111-root04/summary.json、/tmp/pdf-existing-image-browser-20261111-root05/summary.json；manifest e2af5a7a9380fde26ee45022598c5ebd78ed24ede6fda02141b480cc425491f3。各自资产逐个与磁盘 SHA 核对、清单前后不变；共享工作树其他会话重建使两批清单不同，未混称同一构建。
- 保护新增四项后置故障、HTTP 三故障，转换 HTTP 五故障、发布合同两组 44 / 28 项、图片 HTTP 正常两项/非法参数五项及新增宿主专项均通过；只运行受影响专项，未重跑完整项目测试。详细日志见本轮对应 /tmp/pdf-*20261111.log。
- 隔离 PDF Docker-stage 等价目录无兄弟 node_modules，独立 bundle/package/真实转换及 python-pptx 通过；完整容器镜像和 Node 22 容器未重建，实际验证 Node 24。来源转换许可与哈希清单已随独立包保存。
- 本轮 Vite 生产构建成功，PDF 定向类型检查通过。全量 tsc 的 Word/PPT 测试类型错误记录于 /tmp/pdf-final-types-20261111.log；未改这些并行模块。最终共享资产预算检查：PDF 228.7 KiB 在 250 KiB 内，但 workbook-main 253.1 KiB 超过现有 253 KiB；记录 /tmp/pdf-alignment-budget-final-20261111.log，未放宽预算。
- 表单资源间接引用规范化、图像无损压缩误判及保护生成后回执/复核异常阻断均已修根因并保留历史 RED / 浏览器失败证据。下载仍声明业务/完整保真验收待核验，不标记验收通过。未提交、未部署、未开启生产功能开关。
