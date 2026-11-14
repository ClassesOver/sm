# PPTX 背景格式窗口：PC 布局与真实文件检查

从 frontend 目录运行，指定已核对的构建目录、manifest SHA 及全新证据目录：

```bash
TMPDIR=/dev/shm \
PPTX_BACKGROUND_STATIC=/dev/shm/本次构建 \
PPTX_BACKGROUND_EXPECTED_MANIFEST_SHA256=已核对的manifest摘要 \
PPTX_BACKGROUND_DIRECTORY=/dev/shm/全新证据目录 \
node smoke/office-pptx-background-smoke.mjs
```

默认使用真实构建宿主、Python inspect/patch/render-tree 和实际 HTTP 附件。HTTP 授权、上下文、CSRF、修订登记和保存应答是显式夹具，初始 preview.pdf GET 返回204；不代表生产授权、数据库、PDF转换或桌面 PowerPoint 实机验收。

检查图片、渐变、无效图片错误、选图等待、重开图片及重开渐变六状态，每种覆盖五种视口。检查固定标题/操作、中部滚动、520px桌面宽度、28px控件、16px复选框、主题字体、焦点环、Tab循环、输入/草稿保持。五点命中位于控件真实圆角内部，不把包围盒圆角外的空白误判为遮挡；每点坐标及命中结果入证据。截图需要人工复核。

真实操作包含取消/Esc/标题关闭回焦、取消后选图才返回时草稿不变、无效图片后重试、全页平铺背景图、第二页45°渐变、第三页重置背景、隐藏背景图形，以及每步Undo/Redo和刷新恢复。保存一次，验收告警须明确展示并仍允许下载。新修订回显图片模式、渐变颜色/方向及背景图形状态，且草稿为空。

`office-pptx-background-fixture.py` 用独立 ZIP/XML/python-pptx 核对上传图片原字节、背景节点之外的全部对象XML、对象几何、正文、讲稿、链接、原媒体、母版及版式等非目标部件。目标是背景与背景图形标记；不能把形状本身的变化混入本检查。实际保存文件只允许三页背景XML、第一页背景图片关系和必要内容类型声明改变，新增唯一背景媒体。

校验器故障注入不保存任何新修订，也不改原产物：

```bash
TMPDIR=/dev/shm PYTHONDONTWRITEBYTECODE=1 \
../../../.venv/bin/python smoke/office-pptx-background-verifier-faults.py /dev/shm/已有成功证据目录
```

`PPTX_BACKGROUND_BASELINE=1` 只记录初始图片/渐变布局缺陷，禁止保存；退出0只代表记录完成，`ok=false`，不能算验收通过。已存在保存回执或修订2的目录禁止普通重跑。保存后失败，应保留回执与文件，可加 `PPTX_BACKGROUND_REVIEW_ONLY=1` 只读下载/独立校验/新修订回显；保存路由在该模式强制拒绝写入。证据JSON描述最后一次运行，初次保存日志及步骤回执需保留，不把只读复核当成新的保存。

选图与解码后关闭窗口的两个异步边界另由 `slides-background-dialog.test.ts` 覆盖；其中图片选择/解码是受控异步依赖，不能将其说成真实图片解码性能或真实用户的系统文件选择器测试。
