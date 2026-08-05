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
`report-artifact:manifest` 验证实际交付路径、citation、MetricFact、事实表格和图表事实绑定，
再调用 `finish_task`。最终 PDF 隐藏协议 marker，权威 Markdown 和 Manifest 保留完整事实血缘。

成稿只读取 `analysisFactSetRef.path` 指向的紧凑分析目录；完整 FactSet 和原始物化数据集仅供服务端
审计，不得读取或重新聚合。事实表格只提交表头、行标签和 publishable MetricFact ID，数值由服务端
使用目录中的同一 `displayText` 回填，禁止生成明细数据表或自行提交单元格数值。
