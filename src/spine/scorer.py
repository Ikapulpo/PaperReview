"""Relevance scorer for spine papers against user interest areas.

Interest areas (★ marked):
  1. 脊椎外科とAI (Spine surgery and AI)
  2. 脊椎外科手術の適応評価 (Surgical indication assessment)
  3. 脊椎の基礎研究 (Basic spine research: disc, neural tissue, osteoimmunology/metabolism)
  4. バイオマテリアル (Biomaterials: basic or clinical evaluation)
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)


INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network", "CNN",
            "natural language processing", "NLP",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "image recognition",
            "automated detection", "automated classification",
            "predictive model", "prediction model",
            "radiomics", "deep learning spine",
        ],
        "secondary": [
            "random forest", "support vector machine", "SVM",
            "logistic regression model", "decision tree",
            "XGBoost", "gradient boosting",
            "algorithm", "classifier", "classification model",
            "automated", "automation",
            "augmented reality", "AR navigation",
            "robotic surgery", "robot-assisted",
            "navigation system", "computer-assisted",
        ],
    },
    "手術適応評価": {
        "primary": [
            "surgical indication", "surgical decision",
            "patient selection", "treatment selection",
            "operative criteria", "surgical criteria",
            "indication for surgery", "candidacy for surgery",
            "shared decision making", "clinical decision",
            "prognostic factor", "outcome predictor",
            "risk stratification",
        ],
        "secondary": [
            "conservative vs surgical", "operative vs nonoperative",
            "surgical outcome prediction", "preoperative assessment",
            "treatment algorithm", "clinical pathway",
            "MCID", "minimal clinically important difference",
            "patient-reported outcome", "PROM",
            "cost-effectiveness", "value-based",
            "comparative effectiveness",
            "propensity score", "matched cohort",
        ],
    },
    "脊椎基礎研究": {
        "primary": [
            "intervertebral disc", "nucleus pulposus", "annulus fibrosus",
            "disc degeneration", "disc regeneration",
            "notochordal cell", "disc cell",
            "spinal cord injury", "nerve root",
            "dorsal root ganglion", "DRG",
            "neuropathic pain mechanism", "neuroinflammation",
            "osteoclast", "osteoblast", "osteocyte",
            "bone metabolism", "bone remodeling",
            "osteoimmunology", "RANKL", "OPG",
            "bone morphogenetic protein", "BMP",
            "Wnt signaling", "bone formation",
        ],
        "secondary": [
            "cell culture", "in vitro", "in vivo",
            "animal model", "rat model", "mouse model",
            "tissue engineering", "stem cell",
            "mesenchymal stem cell", "MSC",
            "gene expression", "signaling pathway",
            "inflammatory cytokine", "TNF-α", "IL-1β", "IL-6",
            "apoptosis", "autophagy", "senescence",
            "extracellular matrix", "collagen", "proteoglycan",
            "biomechanics", "finite element",
            "spinal fusion biology", "ossification",
            "ossification of posterior longitudinal ligament", "OPLL",
            "bone graft", "bone healing",
            "osteoporosis", "bone mineral density",
            "vitamin D", "PTH", "parathyroid",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "biocompatibility",
            "scaffold", "hydrogel", "nanofiber",
            "3D printing", "3D-printed", "additive manufacturing",
            "bioactive material", "biodegradable",
            "titanium alloy", "PEEK", "polyetheretherketone",
            "calcium phosphate", "hydroxyapatite",
            "bone substitute", "bone graft substitute",
            "interbody cage", "spinal implant",
            "surface modification", "coating",
            "drug delivery", "controlled release",
        ],
        "secondary": [
            "implant design", "implant material",
            "osseointegration", "biointegration",
            "porous structure", "porosity",
            "mechanical testing", "fatigue testing",
            "corrosion", "wear debris",
            "composite material", "polymer",
            "collagen scaffold", "gelatin",
            "growth factor delivery", "BMP delivery",
            "injectable", "cement",
            "vertebroplasty material", "kyphoplasty",
        ],
    },
}


@dataclass
class ScoredSpinePaper:
    """Scoring result for a spine paper."""

    paper: SpinePaper
    is_starred: bool = False
    matched_interests: list[str] = field(default_factory=list)
    interest_scores: dict[str, float] = field(default_factory=dict)
    top_score: float = 0.0

    @property
    def primary_interest(self) -> str:
        if not self.interest_scores:
            return ""
        return max(self.interest_scores, key=self.interest_scores.get)


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: SpinePaper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


STAR_THRESHOLD = 0.15


class SpineRelevanceScorer:
    """Scores spine papers against interest areas."""

    TITLE_MULTIPLIER = 2.5

    def score_paper(self, paper: SpinePaper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = _build_searchable_text(paper)

        for interest_name, profile in INTEREST_PROFILES.items():
            score = self._score_interest(paper, full_text, profile)
            result.interest_scores[interest_name] = score
            if score >= STAR_THRESHOLD:
                result.matched_interests.append(interest_name)

        result.top_score = max(result.interest_scores.values()) if result.interest_scores else 0.0
        result.is_starred = len(result.matched_interests) > 0
        return result

    def _score_interest(self, paper: SpinePaper, full_text: str, profile: dict) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.25 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.10 * mult
        return min(score, 1.0)

    def score_and_partition(self, papers: list[SpinePaper]) -> tuple[list[ScoredSpinePaper], list[ScoredSpinePaper]]:
        """Score all papers and partition into starred (interest match) and unstarred.

        Returns (starred_papers, unstarred_papers), each sorted by score descending.
        """
        scored = [self.score_paper(p) for p in papers]
        starred = sorted(
            [s for s in scored if s.is_starred],
            key=lambda x: x.top_score,
            reverse=True,
        )
        unstarred = sorted(
            [s for s in scored if not s.is_starred],
            key=lambda x: x.paper.pub_date,
            reverse=True,
        )
        logger.info(
            f"Scored {len(scored)} papers: {len(starred)} starred, {len(unstarred)} unstarred"
        )
        return starred, unstarred
