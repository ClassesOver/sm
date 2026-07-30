---
name: report-artifact
description: 验证 Reporting Workflow 的 Markdown、图表和 ReportArtifactManifest 交付契约。
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

该技能只提供服务端固定 validator。生成全部产物后，使用任务验收契约声明的
`report-artifact:manifest` 验证实际交付路径，再调用 `finish_task`。
