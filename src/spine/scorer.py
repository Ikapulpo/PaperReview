"""Relevance scoring for spine papers against user's interest areas.

Interest areas (★ marked):
  - 脊椎外科とAI
  - 脊椎外科手術の適応評価
  - 脊椎の基礎研究（椎間板組織、神経組織、骨免疫・骨代謝など）
  - バイオマテリアル
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.search import SpinePaper

logger = logging.getLogger(__name__)


INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "natural language processing",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "image recognition",
            "automated diagnosis", "predictive model",
            "clinical decision support", "AI-assisted",
        ],
        "secondary": [
            "convolutional neural", "random forest",
            "support vector machine", "logistic regression model",
            "radiomics", "automated segmentation",
            "image classification", "prediction algorithm",
            "data-driven", "algorithm",
        ],
        "context": [
            "prediction", "classification", "accuracy",
            "AUC", "ROC", "sensitivity", "specificity",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "operative indication",
            "surgical decision", "patient selection",
            "treatment decision", "indication for surgery",
            "conservative versus operative",
            "surgical versus nonsurgical",
            "shared decision making",
            "decision-making tool",
            "operative versus nonoperative",
        ],
        "secondary": [
            "treatment outcome predictor", "prognostic factor",
            "cost-effectiveness", "QALY",
            "minimal clinically important difference", "MCID",
            "clinical pathway", "treatment algorithm",
            "risk stratification", "comparative effectiveness",
        ],
        "context": [
            "outcome prediction", "selection criteria",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "nucleus pulposus",
            "annulus fibrosus", "disc degeneration",
            "disc regeneration", "notochordal cell",
            "spinal cord injury", "nerve root",
            "dorsal root ganglion", "neuropathic pain",
            "osteoclast", "osteoblast", "osteocyte",
            "bone remodeling", "bone metabolism",
            "osteoimmunology", "RANKL", "OPG",
        ],
        "secondary": [
            "mesenchymal stem cell", "cell therapy",
            "tissue engineering", "growth factor",
            "gene expression", "signaling pathway",
            "inflammatory cytokine", "TNF", "IL-1", "IL-6",
            "Wnt signaling", "BMP", "TGF-beta",
            "extracellular matrix", "collagen",
            "proteoglycan", "aggrecan",
            "apoptosis", "senescence", "autophagy",
            "oxidative stress", "hypoxia",
            "animal model", "in vitro", "in vivo",
            "bone mineral density", "osteoporosis mechanism",
        ],
        "context": [
            "molecular", "cellular", "biological",
            "pathophysiology", "mechanism", "pathway",
            "expression", "differentiation",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "biocompatibility",
            "scaffold", "hydrogel", "bioactive",
            "bone graft substitute", "synthetic graft",
            "ceramic", "hydroxyapatite", "tricalcium phosphate",
            "3D printing", "additive manufacturing",
            "biodegradable implant", "resorbable",
            "surface modification", "coating",
        ],
        "secondary": [
            "titanium alloy", "PEEK",
            "bone cement", "PMMA",
            "porous structure", "osseointegration",
            "drug delivery", "controlled release",
            "nanoparticle", "nanofiber",
            "bioink", "bioprinting",
            "mechanical property", "Young's modulus",
            "degradation rate", "cytocompatibility",
            "implant material", "cage material",
        ],
        "context": [
            "material", "polymer", "composite",
            "porosity", "stiffness", "strength",
        ],
    },
}

GENERAL_TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative", "spondylosis", "stenosis", "disc herniation",
            "spondylolisthesis", "radiculopathy", "myelopathy",
            "degenerative disc disease", "facet joint",
        ],
    },
    "Deformity": {
        "keywords": [
            "scoliosis", "kyphosis", "deformity", "sagittal balance",
            "coronal balance", "pelvic incidence", "spinal alignment",
            "adolescent idiopathic scoliosis", "adult spinal deformity",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture", "trauma", "burst fracture", "dislocation",
            "spinal cord injury", "traumatic", "instability",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor", "metastasis", "metastatic", "neoplasm",
            "primary spine tumor", "intradural", "extramedullary",
        ],
    },
    "Infection": {
        "keywords": [
            "spondylodiscitis", "osteomyelitis", "pyogenic",
            "epidural abscess", "surgical site infection",
            "spinal infection", "vertebral infection",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporotic", "vertebral fracture", "compression fracture",
            "osteoporosis", "vertebroplasty", "kyphoplasty", "OVF",
            "bone density", "fragility fracture",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical", "anterior cervical", "ACDF", "laminoplasty",
            "cervical myelopathy", "cervical radiculopathy",
            "cervical disc", "corpectomy",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar", "PLIF", "TLIF", "XLIF", "OLIF", "ALIF",
            "lumbar fusion", "lumbar stenosis", "lumbar disc",
            "cauda equina",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive", "MIS", "percutaneous",
            "tubular retractor", "MISS",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic", "full-endoscopic", "biportal endoscopic",
            "uniportal", "transforaminal endoscopic",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation", "robot", "robotic", "computer-assisted",
            "augmented reality", "O-arm", "intraoperative CT",
        ],
    },
    "Complications": {
        "keywords": [
            "complication", "revision", "adjacent segment",
            "pseudarthrosis", "nonunion", "hardware failure",
            "reoperation", "dural tear", "CSF leak",
        ],
    },
    "Outcomes": {
        "keywords": [
            "outcome", "patient-reported", "ODI", "VAS", "SF-36",
            "EQ-5D", "satisfaction", "return to work",
            "quality of life", "disability",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics", "biomechanical", "finite element",
            "range of motion", "load", "stiffness",
            "cadaver", "cadaveric", "mechanical testing",
        ],
    },
}


@dataclass
class ScoredSpinePaper:
    """Scoring result for a spine paper."""
    paper: SpinePaper
    is_interest: bool = False
    interest_topics: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    interest_score: float = 0.0

    @property
    def star_mark(self) -> str:
        return "★" if self.is_interest else ""


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: SpinePaper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:
    """Score spine papers against interest areas and assign general topics."""

    TITLE_MULTIPLIER = 2.0
    INTEREST_THRESHOLD = 0.30

    def score_paper(self, paper: SpinePaper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = _build_searchable_text(paper)

        # Score against interest areas
        max_interest_score = 0.0
        for topic_name, profile in INTEREST_PROFILES.items():
            score = self._score_interest_topic(paper, full_text, profile)
            if score >= self.INTEREST_THRESHOLD:
                result.interest_topics.append(topic_name)
                result.is_interest = True
            max_interest_score = max(max_interest_score, score)

        result.interest_score = max_interest_score

        # Assign general topics
        for topic_name, profile in GENERAL_TOPIC_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    result.general_topics.append(topic_name)
                    break

        return result

    def _score_interest_topic(self, paper: SpinePaper, full_text: str, profile: dict) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.3 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.15 * mult
        for term in profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.05
        return min(score, 1.0)

    def score_and_rank(self, papers: list[SpinePaper]) -> list[ScoredSpinePaper]:
        """Score all papers. Returns interest papers first, then others."""
        scored = [self.score_paper(p) for p in papers]

        interest_papers = [s for s in scored if s.is_interest]
        other_papers = [s for s in scored if not s.is_interest]

        interest_papers.sort(key=lambda x: x.interest_score, reverse=True)

        logger.info(
            f"Scored {len(scored)} papers: "
            f"{len(interest_papers)} interest (★), {len(other_papers)} general"
        )
        return interest_papers + other_papers
