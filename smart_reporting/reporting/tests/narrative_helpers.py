"""动态叙事测试工厂；不依赖其他测试模块。"""

from smart_reporting.reporting.hospital_operation.findings import FindingCard, FindingGraph


def finding(number: int = 1, **changes: object) -> FindingCard:
    return FindingCard.model_validate({
        "findingId": f"finding_{number:016x}",
        "analysisIds": [f"analysis_{number:03d}"],
        "kind": "comparison", "title": "收入同比变化", "summary": "收入发生变化",
        "metricCodes": ["income"], "periodRoles": ["current", "yoy"],
        "periodStart": "2025-01-01", "periodEnd": "2025-12-31", "grain": ["院区"],
        "scope": {}, "priority": "high", "evidenceLevel": "verified_fact",
        "actionability": "unknown", "citationIds": ["citation_001"],
        "sourceRefs": [{
            "analysisId": f"analysis_{number:03d}", "fileSha256": "a" * 64,
            "path": "facts.json", "pointer": "/comparisons/0",
        }], **changes,
    })


def graph(*cards: FindingCard) -> FindingGraph:
    return FindingGraph(snapshotHash="b" * 64, findings=cards)
