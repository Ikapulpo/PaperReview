"""Interest-area scoring for spine papers.

Four interest areas (papers matching any get a star):
  1. 脊椎外科とAI
  2. 脊椎外科手術の適応評価
  3. 脊椎の基礎研究（椎間板組織・神経組織・骨免疫/骨代謝）
  4. バイオマテリアルの基礎・臨床評価
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)

INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence",
            "machine learning",
            "deep learning",
            "neural network",
            "natural language processing",
            "large language model",
            "computer vision",
            "convolutional neural network",
            "random forest",
            "gradient boosting",
            "transformer model",
            "GPT",
            "ChatGPT",
            "automated detection",
            "automated classification",
            "automated segmentation",
            "image recognition",
            "predictive model",
            "predictive analytics",
        ],
        "secondary": [
            "CNN",
            "RNN",
            "XGBoost",
            "support vector machine",
            "decision tree",
            "radiomics",
            "deep neural",
            "BERT",
            "foundation model",
        ],
        "context": [
            "automated",
            "computational",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication",
            "patient selection",
            "operative criteria",
            "surgical decision",
            "treatment selection",
            "surgical candidacy",
            "indication for surgery",
            "operative indication",
            "shared decision making",
            "appropriateness criteria",
        ],
        "secondary": [
            "outcome prediction",
            "surgical outcome",
            "prognostic factor",
            "risk stratification",
            "preoperative evaluation",
            "preoperative assessment",
            "patient-reported outcome",
            "PROM",
            "minimal clinically important difference",
            "MCID",
            "cost-effectiveness",
            "value-based",
            "conservative versus surgical",
            "operative versus nonoperative",
            "surgical versus nonsurgical",
            "comparative effectiveness",
            "propensity score",
            "clinical prediction rule",
            "decision analysis",
        ],
        "context": [
            "indication",
            "appropriateness",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc",
            "nucleus pulposus",
            "annulus fibrosus",
            "endplate",
            "disc degeneration",
            "disc regeneration",
            "disc cell",
            "notochordal cell",
            "spinal cord injury",
            "nerve root",
            "dorsal root ganglion",
            "neuropathic pain",
            "osteoclast",
            "osteoblast",
            "osteocyte",
            "RANKL",
            "osteoprotegerin",
            "bone remodeling",
            "bone metabolism",
            "osteoimmunology",
        ],
        "secondary": [
            "disc tissue",
            "cartilage endplate",
            "extracellular matrix",
            "collagen type II",
            "aggrecan",
            "proteoglycan",
            "inflammatory cytokine",
            "TNF-alpha",
            "IL-1beta",
            "IL-6",
            "NF-kB",
            "Wnt signaling",
            "BMP",
            "TGF-beta",
            "mesenchymal stem cell",
            "neural stem cell",
            "axonal regeneration",
            "demyelination",
            "remyelination",
            "neuroinflammation",
            "microglia",
            "astrocyte",
            "Schwann cell",
            "bone mineral density",
            "osteoporosis",
            "calcium metabolism",
            "vitamin D",
            "parathyroid hormone",
            "sclerostin",
            "cathepsin K",
            "bone resorption",
            "bone formation",
            "mechanotransduction",
        ],
        "context": [
            "in vitro",
            "in vivo",
            "animal model",
            "cell culture",
            "signaling pathway",
            "gene expression",
            "molecular mechanism",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial",
            "scaffold",
            "hydrogel",
            "biocompatibility",
            "bone graft substitute",
            "bone substitute",
            "tissue engineering",
            "bioactive glass",
            "calcium phosphate",
            "hydroxyapatite",
            "tricalcium phosphate",
            "3D printing",
            "3D-printed",
            "bioprinting",
            "drug delivery system",
            "growth factor delivery",
            "nanoparticle",
            "nanofiber",
            "electrospinning",
        ],
        "secondary": [
            "implant material",
            "surface coating",
            "titanium alloy",
            "PEEK",
            "polyetheretherketone",
            "polylactic acid",
            "PLA",
            "PLGA",
            "collagen scaffold",
            "gelatin",
            "chitosan",
            "silk fibroin",
            "decellularized",
            "osseointegration",
            "osteoinduction",
            "osteoconduction",
            "degradation",
            "biodegradable",
            "bioresorbable",
            "bioceramics",
            "bone cement",
            "polymethylmethacrylate",
            "PMMA",
            "allograft",
            "autograft",
            "xenograft",
            "demineralized bone matrix",
            "DBM",
            "recombinant human BMP",
            "rhBMP-2",
        ],
        "context": [
            "coating",
            "porosity",
            "mechanical properties",
        ],
    },
}


@dataclass
class SpineScoredArticle:
    """Scoring result for a spine paper."""

    paper: SpinePaper
    total_score: float = 0.0
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    is_starred: bool = False

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return ""
        return max(self.topic_scores, key=self.topic_scores.get)


def _text_contains(text: str, keyword: str) -> bool:
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def _build_searchable_text(paper: SpinePaper) -> str:
    return " ".join(
        [
            paper.title,
            paper.abstract,
            " ".join(paper.keywords),
            " ".join(paper.mesh_terms),
        ]
    )


class SpineScorer:

    TITLE_MULTIPLIER = 2.0
    SCORE_THRESHOLD = 0.25

    def score_paper(self, paper: SpinePaper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for topic_name, profile in INTEREST_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        result.total_score = (
            max(result.topic_scores.values()) if result.topic_scores else 0.0
        )
        result.is_starred = len(result.matched_topics) > 0
        return result

    def _score_topic(
        self, paper: SpinePaper, full_text: str, profile: dict
    ) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = (
                    self.TITLE_MULTIPLIER
                    if _text_contains(paper.title, term)
                    else 1.0
                )
                score += 0.3 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = (
                    self.TITLE_MULTIPLIER
                    if _text_contains(paper.title, term)
                    else 1.0
                )
                score += 0.15 * mult
        for term in profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.05
        return min(score, 1.0)

    def score_and_partition(
        self, papers: list[SpinePaper]
    ) -> tuple[list[SpineScoredArticle], list[SpineScoredArticle]]:
        """Score all papers and partition into starred / unstarred groups.

        Returns (starred, unstarred), each sorted by score descending.
        """
        scored = [self.score_paper(p) for p in papers]

        starred = sorted(
            [s for s in scored if s.is_starred],
            key=lambda x: x.total_score,
            reverse=True,
        )
        unstarred = sorted(
            [s for s in scored if not s.is_starred],
            key=lambda x: x.total_score,
            reverse=True,
        )

        logger.info(
            f"Scored {len(scored)} papers: {len(starred)} starred, "
            f"{len(unstarred)} unstarred"
        )
        return starred, unstarred
