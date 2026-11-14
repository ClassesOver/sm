# PDF Batch Form Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 多个表单字段共用一个草稿、预览、保存；画布独立修改/移动/删除，Ctrl连续放置真正可用，为复制/重复/粘贴提供基础。
**Architecture:** 后端预校验原来源、全部名称/页/矩形/字段配置，再顺序复用createDesignField并仅由引擎重绑中间SHA/页；回执映射原索引，后续失败保留前序字节。前端创建操作仅与创建互相组合，按唯一fieldName绑定画布目标；继续使用NativeDraft历史和原发布链。
**Tech Stack:** TypeScript, pdf-lib, NativeDraft, React FormDesignLayer, Vitest, node:test, Python.
**Spec:** 本文Design。

## Design
支持text/checkbox/date/choice/radio/signature的既有安全来源边界，不开放任意表单结构。沿用500项操作预算；字段名/父子前缀不能互相冲突，radio子Widget也必须引用原始页。字段名称是本草稿稳定身份；重建来源数据由原SHA和模型绑定。既有字段属性编辑/排列仍按原有独占规则；创建草稿仅可调整本批待保存字段。删除或取消一个新字段不清空其余字段，只有radio“取消新建组”删除该组。

## Global Constraints
保留前批修改，不改固定源writer/发布/签发，不新增依赖；不提交部署，定向验证。

## Review Focus
后段伪造和命名冲突零写入；radio跨页重绑；后段失败保留前段；画布条目索引不可写错；Ctrl连续创建、属性/拖动/删除不得覆盖其他字段；恢复与确认摘要绑定全批。

### Task 1: 引擎
- [x] form-batch-create.test.ts添加多类型跨页/原索引/摘要、全批预校验、后续失败保留RED。
- [x] 新form-batch-create.ts复用已有writer；operations.ts纯创建批次路由，登记默认测试。
- [x] 定向引擎GREEN。

### Task 2: 前端
- [x] 批创建/同名和前缀冲突/替换与删除单字段/恢复测试RED。
- [x] form-create.ts纯批创建验证/追加/精确替换删除；form-design-canvas.ts遍历所有字段并按名称编辑；main创建入口仅放行纯创建草稿。
- [x] 控件、canvas和host定向测试GREEN。

### Task 3: 验收
- [x] 实际引擎与服务预览确认保存下载/独立回读，真实浏览器连续创建/编辑删除，独立审查重要问题。
- [x] 更新缺口：本批仅多字段创建基础，复制/重复/粘贴仍需后续接入，不提前记为完成。

## Results
- 引擎旧独占限制RED；前端追加/画布多字段/公共入口均RED后实现GREEN。
- 引擎8通过（4个批创建专项及原创建4项），包括层级名字、多类型跨页、radio Widget重绑、全输入零写入预校验、后段失败保留实际首字段。
- 首次故障注入在首字段写后复核就触发，诚实产生索引0警告；将故障定位到第二次及以后save，未放宽实际字节/原索引断言。
- 前端6文件117通过，含连续Ctrl放置、属性/位移/删除精确绑定、来源/预算/恢复/公共按钮。旧同名创建测试从单独保存错误改为重复名称错误，不再期待已解除的独占限制。React act警告保留。
- 独立代码审查无重要发现；实际浏览器及服务保存下载通过。全局tsc日志与上一批逐字节相同，仍有632条既有诊断。
- 本批未把复制/重复/粘贴记为完成；继续推进其源字段/待保存字段的安全语义。
