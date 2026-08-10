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

该技能只提供服务端固定 validator。生成全部成稿产物后，使用任务验收契约声明的
`report-artifact:manifest` 验证实际交付路径、citation 和图表引用，
再调用 `finish_task`。PDF 和 Word 由 Workflow 在同一 revision 中从该 Markdown 确定性生成并联合验收；
模型不得自行生成、修改或发布任一成品。最终 PDF/Word 隐藏协议 marker，权威 Markdown 和 Manifest
保留完整数据集血缘。

分析与成稿只读取 Workflow 提供的本轮不可变 CSV。章节按批准提纲顺序逐章生成并绑定
`analysisId`，图表绑定 citation；全部章节完成后由服务端统一拼装 Markdown、PDF 和 Word。
来源差异 Warning 由服务端签发，模型不得隐藏、删除、改写差异数值或扩大授权来源。
