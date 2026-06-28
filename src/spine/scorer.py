"""Interest-area scoring and topic classification for spine papers.

Star (★) areas (user's core interests):
  - 脊椎外科とAI
  - 脊椎外科手術の適応評価
  - 脊椎の基礎研究（椎間板・神経組織・骨免疫/骨代謝）
  - バイオマテリアルの基礎・臨床評価

General topics (for Notion multi-select):
  Degenerative, Deformity, Trauma, Tumor, Infection,
  OVF/Osteoporosis, Cervical, Lumbar, Minimally invasive,
  Endoscopic, Navigation/Robotics, Complications, Outcomes, Biomechanics
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.search import SpinePaper

logger = logging.getLogger(__name__)

# ── Interest areas for ★ marking ─────────────────────────────────────

INTEREST_AREAS: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network",
            "natural language processing", "large language model",
            "LLM", "ChatGPT", "GPT-4", "computer vision",
            "image recognition", "radiomics",
            "automated diagnosis", "automated detection",
        ],
        "secondary": [
            "random forest", "support vector machine",
            "gradient boosting", "XGBoost",
            "decision tree", "classification model",
            "segmentation model", "detection model",
            "transformer", "attention mechanism",
            "robotic surgery AI", "surgical planning AI",
            "predictive model", "prediction model",
            "algorithm", "logistic regression",
        ],
        "context": [
            "prediction", "classification", "accuracy",
            "AUC", "sensitivity", "specificity", "ROC curve",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "operative indication",
            "surgical decision", "treatment decision",
            "patient selection", "surgical candidacy",
            "indication for surgery", "surgical criteria",
            "shared decision", "decision-making",
            "treatment algorithm", "clinical pathway",
        ],
        "secondary": [
            "conservative versus surgical", "operative versus nonoperative",
            "surgical versus nonsurgical",
            "cost-effectiveness", "comparative effectiveness",
            "prognostic factor", "predictive factor",
            "risk stratification", "patient-reported outcome",
            "ODI", "VAS", "NDI", "JOA score", "EQ-5D",
            "MCID", "minimal clinically important difference",
            "clinical guideline", "practice guideline",
        ],
        "context": [
            "indication", "outcome", "prognosis", "selection",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "nucleus pulposus", "annulus fibrosus",
            "disc degeneration mechanism", "disc cell",
            "spinal cord injury model", "nerve root injury",
            "dorsal root ganglion", "neuropathic pain mechanism",
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "OPG", "osteoimmunology",
            "stem cell", "mesenchymal stem cell",
            "cell culture", "tissue engineering",
        ],
        "secondary": [
            "cartilage endplate", "vertebral endplate",
            "notochordal cell", "chondrocyte",
            "extracellular matrix", "collagen", "aggrecan",
            "proteoglycan", "inflammatory cytokine",
            "TNF", "IL-1", "IL-6",
            "apoptosis", "autophagy", "senescence",
            "oxidative stress", "mitochondria",
            "gene expression", "signaling pathway",
            "Wnt", "Notch", "NF-kB", "TGF-beta", "BMP",
            "microRNA", "lncRNA", "epigenetic",
            "mechanobiology", "mechanical loading",
            "pain mechanism", "nociceptor",
            "neuroinflammation", "glial cell", "microglia",
            "in vitro", "in vivo", "animal model",
            "rat model", "mouse model",
        ],
        "context": [
            "molecular", "cellular", "mechanism",
            "pathophysiology", "pathogenesis",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "biocompatibility",
            "scaffold", "hydrogel", "nanoparticle",
            "bioactive", "bioresorbable", "biodegradable",
            "3D printing", "3D-printed", "additive manufacturing",
            "PEEK", "polyetheretherketone",
            "bone graft substitute", "synthetic bone graft",
            "calcium phosphate", "hydroxyapatite", "beta-TCP",
            "bone cement", "PMMA",
            "growth factor delivery", "drug delivery",
            "surface modification", "coating",
        ],
        "secondary": [
            "implant material", "cage material",
            "porous structure", "porosity",
            "mechanical property", "compressive strength",
            "elastic modulus", "fatigue strength",
            "osseointegration", "osteoconduction", "osteoinduction",
            "corrosion", "wear", "degradation",
            "bioactivity", "cell adhesion",
            "cytocompatibility", "histological analysis",
            "titanium alloy", "cobalt chromium",
        ],
        "context": [
            "material", "implant", "graft", "interbody cage",
        ],
    },
}

# ── General spine topics for Notion multi-select ──────────────────────

SPINE_TOPICS: dict[str, list[str]] = {
    "Degenerative": [
        "degenerative", "stenosis", "spondylolisthesis",
        "disc herniation", "radiculopathy", "myelopathy",
        "disc disease", "foraminal stenosis",
    ],
    "Deformity": [
        "scoliosis", "kyphosis", "deformity",
        "sagittal balance", "spinal alignment",
        "coronal balance", "pelvic incidence",
    ],
    "Trauma": [
        "fracture", "trauma", "burst fracture",
        "dislocation", "spinal cord injury",
    ],
    "Tumor": [
        "tumor", "metastasis", "metastatic", "neoplasm",
        "oncologic", "chordoma", "schwannoma",
    ],
    "Infection": [
        "infection", "spondylodiscitis", "osteomyelitis",
        "epidural abscess", "tuberculosis spine",
    ],
    "OVF/Osteoporosis": [
        "osteoporosis", "osteoporotic",
        "vertebral compression fracture",
        "kyphoplasty", "vertebroplasty", "bone density",
    ],
    "Cervical": [
        "cervical", "ACDF", "cervical disc",
        "cervical myelopathy", "cervical stenosis",
        "atlantoaxial", "odontoid",
    ],
    "Lumbar": [
        "lumbar", "PLIF", "TLIF", "XLIF", "OLIF",
        "lumbar fusion", "lumbar stenosis",
        "lumbar disc", "cauda equina",
    ],
    "Minimally invasive": [
        "minimally invasive", "MIS", "MISS",
        "percutaneous", "tubular retractor",
    ],
    "Endoscopic": [
        "endoscopic", "full-endoscopic", "biportal",
        "uniportal", "endoscopy",
    ],
    "Navigation/Robotics": [
        "navigation", "robotic", "robot-assisted",
        "O-arm", "CT-guided", "augmented reality",
    ],
    "Complications": [
        "complication", "revision", "reoperation",
        "adjacent segment", "pseudoarthrosis", "nonunion",
        "dural tear", "CSF leak",
    ],
    "Outcomes": [
        "outcome", "follow-up", "long-term result",
        "quality of life", "patient satisfaction",
        "return to work",
    ],
    "Biomechanics": [
        "biomechanics", "biomechanical", "finite element",
        "cadaveric", "mechanical testing",
        "range of motion",
    ],
}


@dataclass
class ScoredSpinePaper:
    """Scoring result for a spine paper."""

    paper: SpinePaper
    is_starred: bool = False
    interest_areas: list[str] = field(default_factory=list)
    interest_scores: dict[str, float] = field(default_factory=dict)
    spine_topics: list[str] = field(default_factory=list)

    @property
    def max_interest_score(self) -> float:
        return max(self.interest_scores.values()) if self.interest_scores else 0.0

    def to_dict(self) -> dict:
        return {
            "paper": self.paper.to_dict(),
            "is_starred": self.is_starred,
            "interest_areas": self.interest_areas,
            "spine_topics": self.spine_topics,
            "max_interest_score": self.max_interest_score,
        }


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


class SpineScorer:
    """Scores spine papers against user interest areas and classifies topics."""

    TITLE_MULTIPLIER = 2.0
    INTEREST_THRESHOLD = 0.15

    def score_paper(self, paper: SpinePaper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = " ".join(
            [paper.title, paper.abstract, " ".join(paper.keywords), " ".join(paper.mesh_terms)]
        )

        for area_name, profile in INTEREST_AREAS.items():
            score = self._score_area(paper, full_text, profile)
            result.interest_scores[area_name] = score
            if score >= self.INTEREST_THRESHOLD:
                result.interest_areas.append(area_name)
                result.is_starred = True

        for topic_name, keywords in SPINE_TOPICS.items():
            if any(_text_contains(full_text, kw) for kw in keywords):
                result.spine_topics.append(topic_name)

        return result

    def _score_area(self, paper: SpinePaper, full_text: str, profile: dict) -> float:
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

    def score_and_sort(self, papers: list[SpinePaper]) -> list[ScoredSpinePaper]:
        """Score all papers and sort: ★ papers first, then others."""
        scored = [self.score_paper(p) for p in papers]
        starred = sorted(
            [s for s in scored if s.is_starred],
            key=lambda x: x.max_interest_score,
            reverse=True,
        )
        unstarred = [s for s in scored if not s.is_starred]
        logger.info(
            f"Scored {len(scored)} papers: {len(starred)} starred, {len(unstarred)} unstarred"
        )
        return starred + unstarred
