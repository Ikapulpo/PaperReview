"""Relevance scorer for spine journal papers.

Classifies papers into interest areas (★) and general spine topics
for the 週刊スパイン（メルマガ）Notion database.
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)

# ── Interest areas (★ marking) ────────────────────────────────────────

INTEREST_AREAS: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network", "CNN",
            "natural language processing", "NLP", "large language model",
            "LLM", "ChatGPT", "GPT-4", "computer vision",
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "automated detection",
            "automated segmentation", "automated classification",
            "predictive model", "prediction model",
        ],
        "secondary": [
            "algorithm", "classifier", "decision support",
            "radiomics", "transfer learning", "transformer",
            "image recognition", "object detection",
            "generative AI", "foundation model",
        ],
        "context": [
            "accuracy", "AUC", "ROC", "sensitivity", "specificity",
            "precision", "recall", "F1",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "surgical decision",
            "patient selection", "operative indication",
            "treatment selection", "surgical candidacy",
            "decision-making", "decision making",
            "shared decision", "indication for surgery",
        ],
        "secondary": [
            "conservative versus surgical", "conservative vs operative",
            "cost-effectiveness", "cost effectiveness",
            "value-based", "QALY", "treatment algorithm",
            "clinical guideline", "treatment guideline",
            "outcome prediction", "prognostic factor",
            "risk stratification", "scoring system",
            "clinical prediction rule",
        ],
        "context": [
            "indication", "threshold", "recommendation",
            "criteria", "appropriate use",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "disc degeneration",
            "nucleus pulposus", "annulus fibrosus", "notochord",
            "spinal cord injury", "nerve root", "dorsal root ganglion",
            "bone metabolism", "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "bone remodeling", "bone resorption",
            "osteoimmunology", "stem cell", "mesenchymal stem",
            "induced pluripotent", "iPSC",
        ],
        "secondary": [
            "in vitro", "in vivo", "animal model", "cell culture",
            "tissue engineering", "gene expression", "signaling pathway",
            "growth factor", "cytokine", "extracellular matrix",
            "collagen", "proteoglycan", "apoptosis", "autophagy",
            "inflammatory mediator", "neuropathic pain model",
            "Wnt signaling", "BMP", "TGF-beta",
            "epigenetic", "microRNA", "exosome",
        ],
        "context": [
            "mechanism", "pathophysiology", "histology",
            "immunohistochemistry", "molecular",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "scaffold", "hydrogel",
            "biocompatible", "biodegradable",
            "bone graft substitute", "bone cement",
            "PEEK", "3D-printed", "3D printed",
            "additive manufacturing", "bioprinting",
            "drug delivery system", "controlled release",
        ],
        "secondary": [
            "hydroxyapatite", "beta-tricalcium phosphate",
            "bioactive glass", "ceramic", "titanium alloy",
            "surface modification", "coating",
            "composite material", "porous structure",
            "bone substitute", "synthetic graft",
            "bioresorbable", "nanoparticle",
            "tissue scaffold", "decellularized",
        ],
        "context": [
            "biocompatibility", "porosity", "degradation",
            "mechanical properties", "osseointegration",
        ],
    },
}

# ── General topic classification ──────────────────────────────────────

GENERAL_TOPICS: dict[str, list[str]] = {
    "Degenerative": [
        "degenerative", "stenosis", "herniation", "spondylosis",
        "myelopathy", "radiculopathy", "disc disease", "spondylolisthesis",
        "foraminal stenosis", "canal stenosis",
    ],
    "Deformity": [
        "deformity", "scoliosis", "kyphosis", "lordosis",
        "sagittal balance", "coronal balance", "spinal alignment",
        "sagittal vertical axis", "pelvic incidence",
    ],
    "Trauma": [
        "trauma", "burst fracture", "dislocation",
        "spinal cord injury", "unstable injury", "vertebral fracture",
        "traumatic", "thoracolumbar fracture",
    ],
    "Tumor": [
        "tumor", "neoplasm", "metastasis", "metastatic",
        "chordoma", "schwannoma", "meningioma", "ependymoma",
        "primary bone tumor", "spinal tumor",
    ],
    "Infection": [
        "spondylodiscitis", "osteomyelitis", "epidural abscess",
        "spinal infection", "pyogenic", "tuberculous spondylitis",
    ],
    "OVF/Osteoporosis": [
        "osteoporotic", "osteoporosis", "compression fracture",
        "kyphoplasty", "vertebroplasty", "bone mineral density",
        "DEXA", "osteoporotic vertebral fracture", "OVF",
    ],
    "Cervical": [
        "cervical", "ACDF", "anterior cervical",
        "cervical myelopathy", "cervical disc",
        "cervical laminoplasty", "cervical arthroplasty",
    ],
    "Lumbar": [
        "lumbar", "PLIF", "TLIF", "XLIF", "OLIF", "ALIF",
        "lumbar fusion", "lumbar stenosis", "lumbar disc",
    ],
    "Minimally invasive": [
        "minimally invasive", "MIS", "percutaneous",
        "tubular retractor", "MIS-TLIF",
    ],
    "Endoscopic": [
        "endoscopic", "full-endoscopic", "uniportal",
        "biportal", "endoscopy",
    ],
    "Navigation/Robotics": [
        "navigation", "robotic", "robot-assisted",
        "augmented reality", "computer-assisted", "O-arm",
        "CT navigation",
    ],
    "Complications": [
        "complication", "revision", "reoperation",
        "adjacent segment", "pseudarthrosis", "nonunion",
        "hardware failure", "implant failure",
    ],
    "Outcomes": [
        "patient-reported outcome", "PRO", "ODI", "VAS",
        "SF-36", "JOA score", "quality of life",
        "return to work", "functional outcome",
    ],
    "Biomechanics": [
        "biomechanics", "biomechanical", "finite element",
        "cadaveric", "range of motion", "stiffness",
        "load sharing", "stress distribution",
    ],
}


@dataclass
class SpineScoredArticle:
    paper: Paper
    is_starred: bool = False
    interest_areas: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    title_ja: str = ""
    abstract_summary: str = ""

    @property
    def all_topics(self) -> list[str]:
        return sorted(set(self.interest_areas + self.general_topics))

    @property
    def star_label(self) -> str:
        if self.interest_areas:
            return "★ " + " / ".join(self.interest_areas)
        return ""


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:

    TITLE_MULTIPLIER = 2.0
    INTEREST_THRESHOLD = 0.15
    TOPIC_THRESHOLD = 0.10

    def score_paper(self, paper: Paper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable(paper)

        for area_name, profile in INTEREST_AREAS.items():
            score = self._score_profile(paper, full_text, profile)
            if score >= self.INTEREST_THRESHOLD:
                result.interest_areas.append(area_name)

        result.is_starred = len(result.interest_areas) > 0

        for topic_name, keywords in GENERAL_TOPICS.items():
            if any(_text_contains(full_text, kw) for kw in keywords):
                result.general_topics.append(topic_name)

        return result

    def _score_profile(self, paper: Paper, full_text: str, profile: dict) -> float:
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

    def score_all(self, papers: list[Paper]) -> list[SpineScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]
        result = starred + unstarred
        star_count = len(starred)
        logger.info(f"Scored {len(scored)} papers: {star_count} starred, {len(unstarred)} general")
        return result
