# XLSX 普通图片、公式、图标

固定参考源 `/home/junge/pros/genoffice-source-full`，提交 `f8c17004fb730df11f0f743164ffd8b4281bb38c`。完整移植 XLSX EquationDialog、IconsDialog、图标目录及 modal 行为，中文适配及 Promise 提交；本地 PNG/JPEG 通过普通 drawing 插入。公式以 PNG 保存，不宣称可编辑 OMML。公式/图标对话框失败留在原界面，事务成功才关闭。

普通图片实现复用底层 `applyStaticImage`，没有借用 VML/批注图片或报告路径型 `applyStaticImages`。请求仅含受控 PNG/JPEG 字节、媒体/尺寸/hash 身份及整个工作簿来源身份。服务端验证实际 PNG/JPEG 格式、40MP/边长预算、verify 后完整解码；浏览器/CLI 校验字节身份。任意 XML prefix 通过 URI 解析；外部图片、越界来源、错误 drawing namespace、非法来源锚点不导入显示，保留原包。

Univer 原生 drawing 显示已有及新图片，复用现有工作簿事务、history、失败回滚和保存重开。当前明确禁止普通图片拖移/删除，避免未持久化修改；公式和图标按 PNG 保存的限制也在成功反馈中说明。

## 验证

- `source-native/evidence.json`：真实 Chromium 产品 UI，公式、9分类图标搜索/红色选择、本地 PNG、undo/redo、3视口 modal 取消与重开；保存调用真实 `native_office.patch_office` → source CLI，独立 openpyxl/ZIP 检查 4 images / 1 chart / 4 media，正文、其他页公式、旧批注保留。
- HTTP 授权/context/file 与修订仓储是明确夹具；不宣称生产服务持久化或下载签发验收。
- 保存 XLSX SHA256 `365bd5c59b35a6422f9b2c7a9ca7a6cc41789694287458574ad60da4c10cc50b`。
- `source-native/zip-preservation.json`：原 PNG、chart XML、comments XML、VML 逐字节相同，原 drawing 锚点完整保留。新增公式 230×72、1776 可见像素；图标 256×256、11137 红色可见像素；本地 PNG 1×1 有效像素。
- engine `bridge/pictures.test.ts`：3 passed，覆盖真实 drawing / 连续插入 / 原批注保真 / 身份拒绝 / 任意prefix / 外部和伪造namespace拒用 / 非整数与越界来源锚点。
- Python `test_native_xlsx_pictures.py`：3 passed，含正常PNG/JPEG完整解码与header可读截断文件拒绝。
- frontend `workbook-pictures.test.ts`：1 passed，受控媒体身份及 URL/MIME伪装拒绝（此前执行）。engine package tsc通过（此前执行）。不宣称 frontend 全量 tsc 通过。
- 最终 built 验证待父 agent 冻结产物后追加。

历史失败 `attempt2-hmr-failure.json` 与 `attempt3-hmr-failure.*` 是开发服务器重启/测试选择器调试记录，最终 source evidence ok=true。
