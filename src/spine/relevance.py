"""Relevance scoring for spine surgery papers.

Classifies papers into interest areas and marks ★ for:
  - 脊椎外科とAI
  - 脊椎外科手術の適応評価
  - 脊椎の基礎研究（椎間板組織や神経組織、骨免疫・骨代謝など）
  - バイオマテリアルの基礎・または臨床評価
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)


INTEREST_TOPICS: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network", "CNN",
            "natural language processing", "NLP",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "automated", "automation",
            "predictive model", "prediction model",
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "SVM",
            "decision tree", "logistic regression model",
            "radiomics", "deep neural",
        ],
        "secondary": [
            "algorithm", "classification model",
            "image recognition", "image segmentation",
            "preoperative planning", "surgical planning AI",
            "robot", "robotic", "navigation",
            "augmented reality", "mixed reality",
            "digital twin", "computational model",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "surgical decision",
            "patient selection", "operative criteria",
            "treatment algorithm", "clinical decision",
            "surgical candidacy", "appropriate use criteria",
            "shared decision making", "decision-making",
            "cost-effectiveness", "cost effectiveness",
            "value-based", "QALY",
            "patient-reported outcome", "PRO",
            "MCID", "minimal clinically important difference",
            "predictive factor", "prognostic factor",
            "outcome predictor",
        ],
        "secondary": [
            "conservative versus surgical",
            "operative versus nonoperative",
            "surgical versus nonsurgical",
            "indication", "contraindication",
            "risk stratification", "risk factor",
            "clinical outcome", "functional outcome",
            "comparative effectiveness",
            "propensity score", "registry",
            "nationwide database", "administrative database",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "intervertebral disk",
            "nucleus pulposus", "annulus fibrosus", "anulus fibrosus",
            "disc degeneration", "disk degeneration",
            "disc regeneration", "disk regeneration",
            "notochordal cell", "disc cell",
            "spinal cord injury", "nerve root",
            "dorsal root ganglion", "DRG",
            "neuropathic pain", "radiculopathy mechanism",
            "osteoclast", "osteoblast", "osteocyte",
            "bone metabolism", "bone remodeling",
            "osteoimmunology", "RANKL", "OPG",
            "bone mineral density mechanism",
            "Wnt signaling", "BMP", "bone morphogenetic protein",
            "mesenchymal stem cell", "MSC",
            "stem cell", "cell therapy",
            "gene therapy", "gene expression",
            "cytokine", "inflammatory mediator",
            "TNF-α", "IL-1", "IL-6",
            "animal model", "in vitro", "in vivo",
            "rat model", "mouse model", "rabbit model",
        ],
        "secondary": [
            "molecular", "cellular", "signaling pathway",
            "extracellular matrix", "collagen",
            "proteoglycan", "aggrecan",
            "apoptosis", "senescence", "autophagy",
            "oxidative stress", "hypoxia",
            "growth factor", "differentiation",
            "tissue engineering", "scaffold",
            "mechanobiology", "biomechanics",
            "finite element", "cadaver",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "bio-material",
            "bone graft substitute", "bone substitute",
            "ceramic", "hydroxyapatite", "HA",
            "tricalcium phosphate", "TCP", "β-TCP",
            "PEEK", "polyetheretherketone",
            "titanium", "titanium alloy",
            "3D printing", "3D-printed", "additive manufacturing",
            "biodegradable", "bioabsorbable", "bioresorbable",
            "coating", "surface modification",
            "cage", "interbody cage",
            "bone graft", "autograft", "allograft",
            "demineralized bone matrix", "DBM",
            "rhBMP-2", "bone morphogenetic protein-2",
            "composite material",
        ],
        "secondary": [
            "implant", "prosthesis", "device",
            "osseointegration", "osteoconduction", "osteoinduction",
            "biocompatibility", "mechanical property",
            "fatigue", "corrosion", "wear",
            "porous", "porosity",
            "fusion rate", "fusion assessment",
            "pseudarthrosis", "nonunion",
            "vertebral body replacement",
            "artificial disc", "disc replacement",
        ],
    },
}


@dataclass
class ScoredSpinePaper:
    """Scoring result for a spine paper."""
    paper: SpinePaper
    is_interest: bool = False
    matched_interests: list[str] = field(default_factory=list)
    interest_score: float = 0.0

    @property
    def star_mark(self) -> str:
        return "★" if self.is_interest else ""


SPINE_CONTEXT_TERMS = [
    "spine", "spinal", "vertebr", "lumbar", "cervical", "thoracic",
    "disc", "disk", "scoliosis", "kyphosis", "lordosis", "stenosis",
    "spondyl", "laminectomy", "laminoplasty", "discectomy", "diskectomy",
    "interbody", "pedicle", "foraminotomy",
    "myelopathy", "radiculopathy", "cauda equina", "spinal cord",
    "sacroiliac", "coccyx", "intervertebral", "paravertebral",
    "lumbar fusion", "cervical fusion", "spinal fusion",
    "thoracolumbar", "lumbosacral", "occipitocervical",
]

SPINE_SPECIFIC_JOURNALS = [
    "Spine", "spine journal", "European spine",
    "neurosurgery. Spine", "Global spine",
]


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _is_spine_relevant(paper: SpinePaper) -> bool:
    """Check if a paper is spine-relevant (important for JBJS filtering)."""
    for j in SPINE_SPECIFIC_JOURNALS:
        if j.lower() in paper.journal.lower():
            return True
    full = f"{paper.title} {paper.abstract} {' '.join(paper.keywords)} {' '.join(paper.mesh_terms)}"
    for term in SPINE_CONTEXT_TERMS:
        if term in ("disc", "disk"):
            if re.search(r"\b" + re.escape(term) + r"\b", full, re.IGNORECASE):
                return True
        else:
            if re.search(re.escape(term), full, re.IGNORECASE):
                return True
    return False


def _build_searchable_text(paper: SpinePaper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineRelevanceScorer:

    TITLE_MULTIPLIER = 2.0

    def score_paper(self, paper: SpinePaper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = _build_searchable_text(paper)

        # For non-spine-specific journals (JBJS), only mark ★ if spine-relevant
        spine_relevant = _is_spine_relevant(paper)

        max_score = 0.0
        for topic_name, profile in INTEREST_TOPICS.items():
            score = self._score_topic(paper, full_text, profile)
            if score > 0.1 and spine_relevant:
                result.matched_interests.append(topic_name)
            max_score = max(max_score, score)

        result.interest_score = max_score if spine_relevant else 0.0
        result.is_interest = len(result.matched_interests) > 0
        return result

    def _score_topic(self, paper: SpinePaper, full_text: str, profile: dict) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.3 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.1 * mult
        return min(score, 1.0)

    def score_and_partition(self, papers: list[SpinePaper]) -> tuple[list[ScoredSpinePaper], list[ScoredSpinePaper]]:
        """Score all papers and partition into interest/non-interest groups.

        Returns (interest_papers, other_papers), each sorted by score desc.
        """
        scored = [self.score_paper(p) for p in papers]
        interest = [s for s in scored if s.is_interest]
        others = [s for s in scored if not s.is_interest]
        interest.sort(key=lambda x: x.interest_score, reverse=True)
        others.sort(key=lambda x: x.paper.pub_date, reverse=True)
        logger.info(
            f"Scored {len(scored)} spine papers: "
            f"{len(interest)} interest ★, {len(others)} other"
        )
        return interest, others
