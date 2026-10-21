"""Server-derived writing boundaries; evidence rank never certifies business causality."""

from __future__ import annotations


def finding_presentation_policy(
    evidence_level: str | None, *, source_unavailable: bool = False,
) -> dict[str, str]:
    """Keep important gaps visible without turning priority into verification.

    A resolvable source is necessary, but does not itself prove the interpretation.
    Unknown/legacy evidence levels therefore receive the same boundary as gaps.
    """
    if source_unavailable:
        return {
            "statementMode": "gap",
            "conclusionBoundary": "来源未完整核实，仅披露证据缺口；不得沿用原发现中的数值、经营结论或原因。",
            "actionBoundary": "核对来源身份及原始记录；补齐证据后再评价，不提出依赖该结论的整改目标。",
        }
    if evidence_level in {"verified_fact", "rule_based", "direct_decomposition"}:
        boundary = {
            "verified_fact": "仅描述冻结事实；事实核实不代表异常性质、风险或因果已经核实。",
            "rule_based": "仅在已登记规则、适用范围和前提内评价；不把规则结果外推为经营原因。",
            "direct_decomposition": "仅解释同范围数值分解及贡献；数值贡献不证明业务因果。",
        }[evidence_level]
        return {
            "statementMode": "bounded_fact",
            "conclusionBoundary": boundary,
            "actionBoundary": "建议须有已核实偏差及适用基准；缺少目标、责任人或期限时保持待确认。",
        }
    if evidence_level == "statistical_relation":
        return {
            "statementMode": "association",
            "conclusionBoundary": "仅陈述统计关联及限制，不认定因果、效率、浪费或风险。",
            "actionBoundary": "建议进一步核查关联，不据此直接制定降本、压减或绩效考核目标。",
        }
    if evidence_level == "business_hypothesis":
        return {
            "statementMode": "hypothesis",
            "conclusionBoundary": "仅作为待验证假设并说明验证条件，不写成摘要或图题中的确定经营结论。",
            "actionBoundary": "提出验证步骤及所需证据，不把假设作为已确认问题安排整改。",
        }
    return {
        "statementMode": "gap",
        "conclusionBoundary": "仅披露证据缺口与影响范围，不把缺失补零或把未知写成正常、达标。",
        "actionBoundary": "优先补齐来源、口径及覆盖证据；不得提出依赖未知结论的管理目标。",
    }
