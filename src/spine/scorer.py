"""Interest-area scorer for spine journal papers.

Classifies papers into the user's four research interest areas:
  1. 脊椎外科とAI           — Spine surgery × AI / machine learning
  2. 脊椎外科手術の適応評価   — Surgical indication / decision-making
  3. 脊椎の基礎研究          — Basic spine research (disc, nerve, bone immunology)
  4. バイオマテリアル        — Biomaterials (basic / clinical evaluation)

Papers matching ANY interest area receive a ★ mark.
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)

# ── Interest-area keyword profiles ──────────────────────────────────────

INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network", "CNN",
            "natural language processing", "NLP",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "image recognition",
            "automated diagnosis", "AI-assisted",
            "predictive model", "prediction model",
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "logistic regression model",
            "decision tree", "ensemble learning",
        ],
        "secondary": [
            "radiomics", "automated segmentation",
            "computer-aided", "computer aided",
            "classification algorithm", "clustering algorithm",
            "transfer learning", "data-driven",
            "robotic surgery", "surgical robot", "navigation system",
            "augmented reality", "mixed reality",
            "preoperative planning software",
        ],
        "context": [
            "algorithm", "model accuracy", "AUC", "ROC",
            "sensitivity specificity", "validation cohort",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "surgical decision",
            "operative indication", "operative criteria",
            "patient selection", "treatment selection",
            "shared decision making", "clinical decision",
            "surgery versus conservative", "operative versus nonoperative",
            "surgical candidacy", "indication for surgery",
            "prognostic factor", "predictive factor",
            "outcome predictor",
        ],
        "secondary": [
            "conservative treatment", "nonoperative treatment",
            "cost-effectiveness", "cost effectiveness",
            "quality of life", "QALY",
            "patient-reported outcome", "PROM",
            "Oswestry disability index", "ODI",
            "visual analog scale", "VAS", "NRS",
            "JOA score", "SF-36", "EQ-5D",
            "minimum clinically important difference", "MCID",
            "risk stratification", "treatment algorithm",
            "clinical guideline", "practice guideline",
            "comparative effectiveness",
        ],
        "context": [
            "outcome", "prognosis", "follow-up",
            "reoperation", "revision surgery",
            "complication rate", "success rate",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "intervertebral disk",
            "nucleus pulposus", "annulus fibrosus",
            "disc degeneration", "disk degeneration",
            "disc herniation", "disk herniation",
            "disc cell", "notochordal cell",
            "spinal cord injury", "nerve root",
            "dorsal root ganglion", "DRG",
            "neuropathic pain", "radiculopathy mechanism",
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "osteoimmunology", "bone immunology",
            "RANKL", "OPG", "osteoprotegerin",
        ],
        "secondary": [
            "disc regeneration", "disc repair",
            "stem cell disc", "mesenchymal stem cell",
            "growth factor spine", "BMP",
            "cartilage endplate", "vertebral endplate",
            "spinal canal stenosis mechanism",
            "neuroinflammation", "inflammatory cytokine",
            "TNF-alpha", "IL-1", "IL-6",
            "macrophage spine", "microglia",
            "Wnt signaling", "Hedgehog signaling",
            "extracellular matrix", "collagen type II",
            "proteoglycan", "aggrecan",
            "apoptosis disc", "senescence disc",
            "oxidative stress spine",
            "animal model spine", "rat model spine",
            "mouse model spine", "in vitro spine",
            "cell culture disc",
            "bone mineral density mechanism",
            "osteoporosis mechanism",
        ],
        "context": [
            "pathophysiology", "molecular mechanism",
            "signaling pathway", "gene expression",
            "in vitro", "in vivo", "ex vivo",
            "histology", "immunohistochemistry",
            "Western blot", "PCR", "RNA-seq",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "bio-material",
            "biocompatibility", "biodegradable",
            "scaffold", "hydrogel",
            "3D printing spine", "3D-printed implant",
            "titanium implant", "PEEK",
            "bone graft substitute", "synthetic bone graft",
            "calcium phosphate", "hydroxyapatite",
            "beta-tricalcium phosphate", "β-TCP",
            "bioactive glass", "bioceramics",
            "bone cement", "polymethylmethacrylate", "PMMA",
        ],
        "secondary": [
            "interbody cage", "cage material",
            "porous structure", "surface modification",
            "coating implant", "osseointegration",
            "fusion rate material", "bone ingrowth",
            "corrosion resistance", "wear debris",
            "drug delivery spine", "controlled release",
            "nanoparticle spine", "nanofiber",
            "tissue engineering spine",
            "collagen scaffold", "fibrin gel",
            "platelet-rich plasma", "PRP spine",
            "bone morphogenetic protein", "rhBMP-2",
            "demineralized bone matrix", "DBM",
            "allograft", "autograft", "xenograft",
        ],
        "context": [
            "implant", "material property",
            "mechanical testing", "compressive strength",
            "biocompatible", "degradation",
        ],
    },
}


# ── Scored paper result ─────────────────────────────────────────────────

@dataclass
class SpineScoredPaper:
    """Scoring result for a spine paper."""

    paper: SpinePaper
    interest_scores: dict[str, float] = field(default_factory=dict)
    matched_interests: list[str] = field(default_factory=list)
    is_starred: bool = False  # True if matches any interest area

    @property
    def primary_interest(self) -> str:
        if not self.interest_scores:
            return ""
        return max(self.interest_scores, key=self.interest_scores.get)

    @property
    def max_score(self) -> float:
        return max(self.interest_scores.values()) if self.interest_scores else 0.0


# ── Scorer ──────────────────────────────────────────────────────────────

def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


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
    """Score spine papers against research interest areas."""

    TITLE_MULTIPLIER = 2.0
    MATCH_THRESHOLD = 0.15  # minimum to consider a match

    def score_paper(self, paper: SpinePaper) -> SpineScoredPaper:
        result = SpineScoredPaper(paper=paper)
        full_text = _build_searchable_text(paper)

        for interest_name, profile in INTEREST_PROFILES.items():
            score = self._score_interest(paper, full_text, profile)
            result.interest_scores[interest_name] = score
            if score >= self.MATCH_THRESHOLD:
                result.matched_interests.append(interest_name)

        result.is_starred = len(result.matched_interests) > 0
        return result

    def _score_interest(
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

    def score_and_sort(
        self, papers: list[SpinePaper]
    ) -> tuple[list[SpineScoredPaper], list[SpineScoredPaper]]:
        """Score all papers and split into starred / unstarred.

        Returns (starred, unstarred) sorted by max_score descending within
        each group.
        """
        scored = [self.score_paper(p) for p in papers]

        starred = sorted(
            [s for s in scored if s.is_starred],
            key=lambda x: x.max_score,
            reverse=True,
        )
        unstarred = sorted(
            [s for s in scored if not s.is_starred],
            key=lambda x: x.paper.journal_short,
        )

        logger.info(
            f"Scored {len(scored)} papers: {len(starred)} starred, "
            f"{len(unstarred)} unstarred"
        )
        return starred, unstarred
