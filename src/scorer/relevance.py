"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests based on:
1. Keyword matching (title, abstract, MeSH terms, keywords)
2. Method relevance
3. Conceptual relevance
"""

import logging
import re
from dataclasses import dataclass, field

from src.config import config
from src.pubmed.client import Paper

logger = logging.getLogger(__name__)

# Method-related terms that indicate specific experimental approaches
METHOD_KEYWORDS = {
    "in_vivo": [
        "in vivo", "mouse model", "murine model", "animal model",
        "knockout", "transgenic", "adoptive transfer",
        "bone marrow transplant", "chimera",
    ],
    "in_vitro": [
        "in vitro", "cell culture", "co-culture", "coculture",
        "stimulation", "activation assay",
    ],
    "flow_cytometry": [
        "flow cytometry", "FACS", "CyTOF", "mass cytometry",
        "spectral flow", "cell sorting",
    ],
    "sequencing": [
        "RNA-seq", "scRNA-seq", "single-cell", "single cell",
        "bulk RNA", "ATAC-seq", "ChIP-seq", "CITE-seq",
        "spatial transcriptomics", "multiome",
    ],
    "imaging": [
        "imaging", "confocal", "intravital", "microscopy",
        "immunofluorescence", "histology", "micro-CT", "μCT",
    ],
    "clinical": [
        "clinical trial", "patient", "cohort", "retrospective",
        "prospective", "case report", "phase I", "phase II", "phase III",
    ],
    "bone_assay": [
        "bone densitometry", "DEXA", "DXA", "micro-CT bone",
        "bone histomorphometry", "TRAP staining",
        "alizarin red", "alkaline phosphatase assay",
        "RANKL assay", "osteoclastogenesis assay",
    ],
}

# Conceptual categories that bridge NKT research to the lab's interests
CONCEPT_BRIDGES = {
    "immune_regulation": {
        "terms": [
            "immune regulation", "immune homeostasis", "tolerance",
            "regulatory", "suppression", "immunomodulation",
            "anti-inflammatory", "pro-inflammatory",
        ],
        "connects_to": ["NKT恒常性維持機能"],
    },
    "tumor_immunity": {
        "terms": [
            "tumor immunity", "anti-tumor", "cancer immunotherapy",
            "tumor microenvironment", "checkpoint",
            "PD-1", "PD-L1", "CTLA-4",
        ],
        "connects_to": ["NKTワクチン"],
    },
    "osteoimmunology": {
        "terms": [
            "osteoimmunology", "bone immune", "bone marrow niche",
            "immune bone interaction", "skeletal immune",
        ],
        "connects_to": ["整形外科", "骨代謝"],
    },
    "cell_therapy": {
        "terms": [
            "cell therapy", "adoptive cell", "CAR-T", "CAR-NKT",
            "cell manufacturing", "GMP", "ex vivo expansion",
        ],
        "connects_to": ["NKTワクチン"],
    },
    "tissue_homeostasis": {
        "terms": [
            "tissue homeostasis", "tissue-resident", "tissue resident",
            "organ homeostasis", "steady state",
        ],
        "connects_to": ["NKT恒常性維持機能"],
    },
}


@dataclass
class RelevanceScore:
    """Detailed relevance score for a paper."""
    paper: Paper
    total_score: float = 0.0
    interest_scores: dict[str, float] = field(default_factory=dict)
    matched_keywords: dict[str, list[str]] = field(default_factory=dict)
    matched_methods: list[str] = field(default_factory=list)
    matched_concepts: list[str] = field(default_factory=list)
    recommendation_reason: str = ""

    @property
    def primary_interest(self) -> str:
        """The research interest most relevant to this paper."""
        if not self.interest_scores:
            return "General NKT"
        return max(self.interest_scores, key=self.interest_scores.get)


def _text_contains(text: str, keyword: str) -> bool:
    """Check if text contains keyword (case-insensitive, word boundary aware)."""
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    return bool(pattern.search(text))


def _build_searchable_text(paper: Paper) -> str:
    """Combine all searchable fields of a paper."""
    parts = [
        paper.title,
        paper.abstract,
        " ".join(paper.keywords),
        " ".join(paper.mesh_terms),
    ]
    return " ".join(parts)


class RelevanceScorer:
    """Scores papers against the lab's research interests."""

    def __init__(self):
        self.interests = config.research_interests

    def score_paper(self, paper: Paper) -> RelevanceScore:
        """Score a single paper against all research interests."""
        result = RelevanceScore(paper=paper)
        full_text = _build_searchable_text(paper)

        # 1. Score against each research interest
        for interest in self.interests:
            name = interest["name"]
            weight = interest["weight"]
            matches = []
            score = 0.0

            for keyword in interest["keywords"]:
                if _text_contains(full_text, keyword):
                    matches.append(keyword)
                    # Title matches are worth more
                    if _text_contains(paper.title, keyword):
                        score += 3.0
                    # Abstract matches
                    elif _text_contains(paper.abstract, keyword):
                        score += 1.5
                    else:
                        score += 0.5

            score *= weight
            result.interest_scores[name] = score
            if matches:
                result.matched_keywords[name] = matches

        # 2. Method scoring
        for method_name, method_terms in METHOD_KEYWORDS.items():
            for term in method_terms:
                if _text_contains(full_text, term):
                    result.matched_methods.append(method_name)
                    break

        # Method bonus: papers using multiple methods or key techniques
        method_bonus = len(result.matched_methods) * 0.5
        if "sequencing" in result.matched_methods:
            method_bonus += 1.0  # Novel tech bonus
        if "bone_assay" in result.matched_methods:
            method_bonus += 1.5  # Direct relevance to bone research

        # 3. Concept bridge scoring
        for concept_name, concept_info in CONCEPT_BRIDGES.items():
            for term in concept_info["terms"]:
                if _text_contains(full_text, term):
                    result.matched_concepts.append(concept_name)
                    # Boost the connected research interests
                    for connected in concept_info["connects_to"]:
                        result.interest_scores[connected] = (
                            result.interest_scores.get(connected, 0) + 2.0
                        )
                    break

        # 4. Calculate total score
        interest_total = sum(result.interest_scores.values())
        concept_bonus = len(result.matched_concepts) * 1.0
        result.total_score = interest_total + method_bonus + concept_bonus

        # 5. Generate recommendation reason
        result.recommendation_reason = self._generate_reason(result)

        return result

    def _generate_reason(self, result: RelevanceScore) -> str:
        """Generate a human-readable recommendation reason in Japanese."""
        parts = []

        # Primary research interest match
        primary = result.primary_interest
        if result.interest_scores.get(primary, 0) > 0:
            matched = result.matched_keywords.get(primary, [])
            if matched:
                top_matches = matched[:3]
                parts.append(f"【{primary}】関連: {', '.join(top_matches)}")

        # Secondary matches
        for name, score in sorted(
            result.interest_scores.items(), key=lambda x: x[1], reverse=True
        ):
            if name != primary and score > 0:
                matched = result.matched_keywords.get(name, [])
                if matched:
                    parts.append(f"【{name}】にも関連: {', '.join(matched[:2])}")

        # Methods
        if result.matched_methods:
            method_names = {
                "in_vivo": "in vivo実験",
                "in_vitro": "in vitro実験",
                "flow_cytometry": "フローサイトメトリー",
                "sequencing": "シーケンシング解析",
                "imaging": "イメージング",
                "clinical": "臨床研究",
                "bone_assay": "骨代謝アッセイ",
            }
            methods_jp = [method_names.get(m, m) for m in result.matched_methods]
            parts.append(f"手法: {', '.join(methods_jp)}")

        # Concept bridges
        if result.matched_concepts:
            concept_names = {
                "immune_regulation": "免疫制御",
                "tumor_immunity": "腫瘍免疫",
                "osteoimmunology": "骨免疫学",
                "cell_therapy": "細胞治療",
                "tissue_homeostasis": "組織恒常性",
            }
            concepts_jp = [concept_names.get(c, c) for c in result.matched_concepts]
            parts.append(f"コンセプト: {', '.join(concepts_jp)}")

        return " | ".join(parts) if parts else "NKT細胞関連論文"

    def score_and_rank(self, papers: list[Paper]) -> list[RelevanceScore]:
        """Score all papers and return sorted by relevance (descending)."""
        scored = [self.score_paper(paper) for paper in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)

        logger.info(
            f"Scored {len(scored)} papers. "
            f"Top score: {scored[0].total_score:.1f}" if scored else "No papers to score."
        )
        return scored
