---
name: report-artifact
description: 验证 Reporting Workflow 的 Markdown、图表和 ReportArtifactManifest 成稿契约。
metadata:
  agentos:
    acceptance:
      validators:
        manifest:
          script: validate_manifest.py
          timeout: 60
          artifactPatterns:
            - 报表/智能分析/*/*
---

# Reporting 产物验收

该技能提供最终权威产物的服务端固定 validator。内部 analysis/section phase 的 acceptance requirement
只承载不可变 phase 参数和阶段产物路径，Report Worker 工具自行核验阶段 JSON 的文件身份；它们不运行
最终 manifest validator。全部章节完成后，Workflow 服务端装配 Markdown 和 Manifest，再在同一
revision 中确定性生成并联合验收 PDF 与 Word。模型不得自行生成、修改或发布任一成品。最终
PDF/Word 隐藏协议 marker，权威 Markdown 和 Manifest 保留完整数据集血缘。

全局 analysis run 只读取 Workflow 提供的本轮不可变 CSV，并冻结 evidence、指标口径、Profile 读取
回执、图表和 citation。每章由独立 section run 消费 `SectionWorkItem`；章节 block 不提交
`analysisId`，该绑定由服务端从批准提纲注入。全部章节完成后由服务端统一拼装 Markdown、PDF 和
Word，未被正文引用的图表排除但不阻断交付。
来源差异 Warning 由服务端签发，模型不得隐藏、删除、改写差异数值或扩大授权来源。
