# Excel 允许用户编辑区域 PC 窗口与文件检查

组件级（真实构造器/CSS，异步回调为夹具）：

```bash
TMPDIR=/dev/shm \
EDITABLE_RANGES_COMPONENT_OUTPUT=/dev/shm/全新组件证据目录 \
node smoke/office-xlsx-editable-ranges-component.mjs
```

覆盖默认、长列表、繁忙、长错误、受保护、密码/权限定义只读六状态和五种视口。检查600px桌面窗口、28px字段、固定标题和操作区、内部滚动、可聚焦说明/状态/错误、焦点环、真实圆角内五点命中、Tab循环、增删回焦及输入保持。初始基线加 `EDITABLE_RANGES_BASELINE=1`，只记录默认状态，不把退出0作为通过。

构建宿主、Univer、真实 Python 保存桥、HTTP下载和重开：

```bash
TMPDIR=/dev/shm \
EDITABLE_RANGES_SMOKE_DIRECTORY=/dev/shm/全新文件证据目录 \
EDITABLE_RANGES_SMOKE_STATIC=/dev/shm/已核对构建 \
EDITABLE_RANGES_EXPECTED_MANIFEST_SHA256=该构建的manifest摘要 \
node smoke/office-xlsx-editable-ranges-smoke.mjs
```

HTTP授权、上下文、CSRF及修订登记/保存应答为显式夹具；不代表生产数据库、桌面Excel实机、完整发布门禁或PDF转换验收。浏览器实际请求的200 JS/CSS需逐个与构建文件SHA一致。构建与测试期间不要修改产品或执行中的脚本。

实际操作包括取消/Esc/标题关闭回入口且草稿不变、真实重复名称报错、修改范围并新增/删除定义、撤销重做和刷新恢复、启用保护、允许范围内值和公式写入、范围外拒绝写入、密码区域只读，以及保存一次。保存应答包含具体的验收失败原因，界面仍应提供生成的文件下载。重开核对数值/公式重算和保护；在新修订草稿暂时撤销保护以回读已保存定义，再Undo恢复原状态，不再次保存。

提交期间 `#report-editor.inert` 会使角色定位暂时无法匹配；脚本等待原始弹窗节点的 `hidden=true` 且宿主解除锁定，不能用可访问角色暂时消失判断提交成功。

独立校验器用ZIP/XML/openpyxl检查范围名称/并集引用、删除效果、保护状态和值/公式，并只允许目标sheet的范围定义、保护节点及B2/E2改变。保留原始B2冻结设置、其他工作表保护、批注、链接、样式、图表、名称、几何与其余部件。校验器反例测试不生成修订：

```bash
TMPDIR=/dev/shm PYTHONDONTWRITEBYTECODE=1 \
../../../.venv/bin/python smoke/office-xlsx-editable-ranges-verifier-faults.py /dev/shm/成功文件证据目录
```

已有保存回执、修订2或下载文件的目录禁止普通重放；保存后失败应保留证据，使用 `EDITABLE_RANGES_REVIEW_ONLY=1` 只读复核下载、独立校验及重开。该模式禁止保存。只读运行的新回执不代表再次创建修订，初次操作步骤和日志仍需保留。
