"""Central compliance-oriented mapping for the controlled ShadowBait fixtures.

This is a technical mapping to privacy-choice and consumer-autonomy principles,
not a legal determination that a page violates CCPA/CPRA.
"""
from __future__ import annotations

from typing import Any, Mapping

COMPLIANCE_MAP: dict[str, dict[str, str]] = {
    "DP01": {
        "category": "False Urgency",
        "principle": "Clear and balanced privacy or purchase choices",
        "description": "Scarcity or countdown signals pressure a decision before the user can evaluate the choice.",
        "harm": "Pressures the user to act quickly instead of making an informed choice.",
        "recommendation": "Use truthful availability information and a fixed, clearly stated end time.",
    },
    "DP02": {
        "category": "Basket Sneaking",
        "principle": "Affirmative and intentional choice",
        "description": "An optional add-on is selected before the user affirmatively chooses it.",
        "harm": "Can add cost or consent without a clear affirmative action.",
        "recommendation": "Leave optional add-ons unchecked and explain them in neutral language.",
    },
    "DP03": {
        "category": "Confirm Shaming",
        "principle": "Understandable and non-manipulative language",
        "description": "The decline option uses guilt or shame to influence the user’s choice.",
        "harm": "Steers the user toward an optional action through emotional pressure.",
        "recommendation": "Use short, neutral choices such as ‘Continue without donation.’",
    },
    "DP05": {
        "category": "Subscription Trap",
        "principle": "Symmetrical start and stop choices",
        "description": "Starting a recurring service is easier or more visible than cancelling it.",
        "harm": "Makes it harder to stop recurring charges than to begin them.",
        "recommendation": "Offer cancellation with the same visibility and simplicity as sign-up.",
    },
    "DP06": {
        "category": "Interface Interference",
        "principle": "Balanced presentation of consequential choices",
        "description": "Visual hierarchy makes one consequential option prominent while muting another.",
        "harm": "Obscures the lower-commitment or privacy-protective alternative.",
        "recommendation": "Give consequential alternatives comparable contrast, size, and clarity.",
    },
    "DP07": {
        "category": "Bait and Switch",
        "principle": "Accurate and consistent choice outcome",
        "description": "The selected offer changes or becomes unavailable at a later step.",
        "harm": "Wastes the user’s time and redirects the decision toward a more expensive outcome.",
        "recommendation": "Keep the advertised outcome available or disclose any change immediately.",
    },
    "DP08": {
        "category": "Drip Pricing",
        "principle": "Clear and complete price disclosure",
        "description": "Mandatory fees appear later instead of with the initial price.",
        "harm": "Prevents an accurate comparison until late in the transaction.",
        "recommendation": "Show the complete payable estimate beside the initial price.",
    },
}

FLIPKART_HEURISTIC_MAP: dict[str, dict[str, str]] = {
    "DP01": {
        "category": "False Urgency",
        "principle": "Truthful availability and time pressure",
        "description": "Scarcity or time language may pressure a purchase decision.",
        "harm": "Can reduce time available to compare options and make an informed choice.",
        "recommendation": "Use only verifiable stock and offer deadlines, stated in neutral language.",
    },
    "DP02": {
        "category": "Basket Sneaking",
        "principle": "Affirmative choice for optional additions",
        "description": "An optional product, service, fee, or protection may be preselected.",
        "harm": "Can add cost or commitment without an intentional customer choice.",
        "recommendation": "Leave optional items unselected and clearly disclose their price.",
    },
    "DP03": {
        "category": "Confirm Shaming",
        "principle": "Neutral and understandable choice language",
        "description": "Decline wording may shame or guilt the customer.",
        "harm": "Can steer a decision through emotional pressure rather than clear consequences.",
        "recommendation": "Use equally neutral labels for accepting and declining an offer.",
    },
    "DP04": {
        "category": "Forced Action",
        "principle": "Necessary and proportionate account requirements",
        "description": "An unrelated account or verification step may be required to continue.",
        "harm": "Can restrict access or collect information beyond what the transaction needs.",
        "recommendation": "Explain why each required step is necessary and offer guest access where practical.",
    },
    "DP05": {
        "category": "Subscription Trap",
        "principle": "Transparent recurring commitment and cancellation",
        "description": "Trial, renewal, or cancellation terms may obscure an ongoing commitment.",
        "harm": "Can cause unexpected recurring charges or make exit difficult.",
        "recommendation": "Disclose renewal timing, amount, and cancellation steps before commitment.",
    },
    "DP06": {
        "category": "Interface Interference",
        "principle": "Balanced presentation of consequential choices",
        "description": "Visual or interaction hierarchy may steer customers toward one choice.",
        "harm": "Can obscure a lower-cost or lower-commitment alternative.",
        "recommendation": "Give consequential choices comparable visibility and clarity.",
    },
    "DP07": {
        "category": "Bait and Switch",
        "principle": "Consistency between advertised and available offer",
        "description": "An advertised product or price may become unavailable or change during selection.",
        "harm": "Can redirect purchase intent to a different or more expensive option.",
        "recommendation": "Keep the advertised offer available or disclose changes clearly before selection.",
    },
    "DP08": {
        "category": "Drip Pricing",
        "principle": "Complete and timely price disclosure",
        "description": "A fee may appear after the initial price is presented.",
        "harm": "Can make comparison difficult until a later purchase step.",
        "recommendation": "Show mandatory fees and the total payable price as early as possible.",
    },
    "DP09": {
        "category": "Disguised Advertisement",
        "principle": "Recognizable commercial content",
        "description": "An advertisement may not be clearly distinguishable from other content.",
        "harm": "Can prevent customers from recognizing commercial persuasion.",
        "recommendation": "Label paid placements clearly and use visual treatment distinguishable from organic content.",
    },
    "DP10": {
        "category": "Nagging",
        "principle": "Respect for declined or dismissed prompts",
        "description": "A prompt may be repeated after a customer declines or dismisses it.",
        "harm": "Can add friction and pressure a customer to accept.",
        "recommendation": "Respect a decline and avoid repeating non-essential prompts.",
    },
    "DP11": {
        "category": "Trick Question",
        "principle": "Clear questions and predictable consequences",
        "description": "Question or option wording may make the intended consequence unclear.",
        "harm": "Can lead a customer to make a choice they did not intend.",
        "recommendation": "Use direct, single-negative questions and describe each option's consequence.",
    },
    "DP12": {
        "category": "SaaS Billing",
        "principle": "Transparent recurring billing",
        "description": "Billing cadence or recurring payment terms may be unclear.",
        "harm": "Can cause unexpected recurring charges or renewal confusion.",
        "recommendation": "State the billing interval, amount, renewal date, and cancellation method together.",
    },
}


def attach_flipkart_heuristic_mapping(
    finding: Mapping[str, Any],
    source: str = "Flipkart 13-category heuristic mapping",
) -> dict[str, Any]:
    result = dict(finding)
    pattern_id = str(result.get("id") or result.get("pattern_id") or "")
    base = dict(FLIPKART_HEURISTIC_MAP.get(pattern_id, {
        "category": str(result.get("name") or "Unmapped pattern"),
        "principle": "Human-readable and balanced choice",
        "description": "This candidate has no category-specific heuristic mapping.",
        "harm": "Requires human review before drawing a conclusion.",
        "recommendation": "Review the captured interface and provide a clear, neutral alternative.",
    }))
    base.update({
        "pattern_id": pattern_id,
        "status": "CANDIDATE",
        "scope": "heuristic technical mapping for human review",
        "source": source,
    })
    result["compliance"] = base
    return result


def mapping_for(pattern_id: str | None, finding: Mapping[str, Any] | None = None) -> dict[str, Any]:
    key = str(pattern_id or "")
    base = dict(COMPLIANCE_MAP.get(key, {
        "category": str((finding or {}).get("name") or "Unmapped pattern"),
        "principle": "Human-readable and balanced choice",
        "description": "This finding has not yet been assigned a project compliance mapping.",
        "harm": "Requires human review before a compliance conclusion.",
        "recommendation": "Review the interface and provide a clear, neutral alternative.",
    }))
    status = str((finding or {}).get("status") or (finding or {}).get("scanner_status") or "CANDIDATE").upper()
    base.update({
        "pattern_id": key,
        "status": status if status in {"VERIFIED", "CANDIDATE", "SIMULATED", "EXCLUDED"} else "CANDIDATE",
        "scope": "technical mapping for human review",
        "source": "project CCPA/CPRA dark-pattern principles mapping",
    })
    return base


def attach_compliance(finding: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(finding)
    pattern_id = result.get("id") or result.get("pattern_id") or result.get("scanner_pattern_id") or result.get("rule_id")
    result["compliance"] = mapping_for(str(pattern_id) if pattern_id else None, result)
    return result


def summarize_compliance(findings: list[Mapping[str, Any]]) -> dict[str, Any]:
    mappings = [item.get("compliance") or mapping_for(str(item.get("id") or item.get("pattern_id")), item) for item in findings]
    return {
        "mapped_findings": len(mappings),
        "verified_mappings": sum(1 for item in mappings if item.get("status") == "VERIFIED"),
        "categories": sorted({str(item.get("category")) for item in mappings}),
        "principles": sorted({str(item.get("principle")) for item in mappings}),
        "scope": "technical mapping for human review; not a legal determination",
    }
