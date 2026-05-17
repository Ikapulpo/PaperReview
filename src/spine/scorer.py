"""Spine paper scorer: general topic classification + ★ interest area detection.

★ Interest areas (user's research focus):
  1. 脊椎外科とAI
  2. 脊椎外科手術の適応評価
  3. 脊椎の基礎研究（椎間板・神経組織・骨免疫/骨代謝）
  4. バイオマテリアル

General topics (Notion database categories):
  Degenerative, Deformity, Trauma, Tumor, Infection, OVF/Osteoporosis,
  Cervical, Lumbar, Minimally invasive, Endoscopic, Navigation/Robotics,
  Complications, Outcomes, Biomechanics
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── ★ Interest area keyword profiles ─────────────────────────────────

INTEREST_AREA_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network",
            "natural language processing", "large language model",
            "computer vision", "ChatGPT", "GPT-4", "GPT-3",
            "AI-assisted", "AI-based", "AI model",
            "automated detection", "automated segmentation",
            "automated classification",
        ],
        "secondary": [
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "logistic regression model",
            "radiomics", "image recognition", "transfer learning",
            "prediction model", "predictive algorithm",
            "transformer model", "foundation model",
            "generative AI", "LLM",
        ],
        "context": [
            "algorithm", "classifier", "segmentation model",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "surgical decision",
            "treatment selection", "operative indication",
            "patient selection", "shared decision making",
            "surgical candidacy", "decision-making tool",
            "surgical vs nonoperative", "surgical vs conservative",
            "operative vs nonoperative",
        ],
        "secondary": [
            "outcome prediction", "prognostic factor",
            "risk stratification", "clinical decision",
            "treatment algorithm", "predictive model",
            "decision analysis", "cost-effectiveness",
            "value-based", "appropriate use criteria",
            "indication criteria", "risk-benefit",
        ],
        "context": [
            "treatment outcome", "decision", "indication",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "disc degeneration",
            "nucleus pulposus", "annulus fibrosus", "notochord",
            "disc cell", "disc biology", "disc regeneration",
            "spinal cord injury model", "nerve root injury",
            "dorsal root ganglion", "neuropathic pain model",
            "bone metabolism", "osteoclast", "osteoblast",
            "RANKL", "osteoimmunology", "osteocyte",
            "bone remodeling",
        ],
        "secondary": [
            "disc tissue", "disc organ culture",
            "growth factor", "cell culture", "stem cell",
            "mesenchymal stem cell", "in vitro", "in vivo",
            "animal model", "rat model", "mouse model",
            "rabbit model", "inflammatory mediator",
            "cytokine expression", "gene expression",
            "signaling pathway", "extracellular matrix",
            "proteoglycan", "collagen type II",
            "Wnt signaling", "BMP", "TGF-beta",
            "apoptosis", "autophagy", "senescence",
            "oxidative stress",
        ],
        "context": [
            "molecular", "cellular", "tissue engineering",
            "regeneration", "pathogenesis",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "biocompatible", "scaffold",
            "bone graft substitute", "bioactive glass",
            "hydroxyapatite", "calcium phosphate",
            "biodegradable implant", "3D printing",
            "bioprinting", "3D-printed",
        ],
        "secondary": [
            "implant material", "PEEK", "bone cement",
            "polymethylmethacrylate", "collagen scaffold",
            "hydrogel", "tissue engineering scaffold",
            "drug delivery system", "coating",
            "surface modification", "titanium alloy",
            "porous structure", "bioabsorbable",
            "bone substitute", "ceramic",
            "composite material", "nanoparticle",
        ],
        "context": [
            "material property", "biocompatibility",
            "degradation", "porosity",
        ],
    },
}

# ── General topic keyword profiles ────────────────────────────────────

GENERAL_TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative", "stenosis", "spondylosis",
            "spondylolisthesis", "disc herniation",
            "herniated disc", "disc protrusion",
            "degenerative disc disease", "foraminal stenosis",
            "central stenosis", "neurogenic claudication",
        ],
    },
    "Deformity": {
        "keywords": [
            "scoliosis", "kyphosis", "deformity",
            "sagittal balance", "sagittal alignment",
            "coronal balance", "spinal deformity",
            "adult spinal deformity", "adolescent idiopathic scoliosis",
            "Cobb angle", "pelvic incidence",
            "sagittal vertical axis", "SVA",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture", "trauma", "traumatic",
            "burst fracture", "chance fracture",
            "spinal cord injury", "vertebral fracture",
            "dislocation", "subluxation",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor", "tumour", "metastasis", "metastatic",
            "chordoma", "osteosarcoma", "schwannoma",
            "meningioma", "intradural", "epidural tumor",
            "spinal tumor", "neoplasm",
        ],
    },
    "Infection": {
        "keywords": [
            "infection", "discitis", "osteomyelitis",
            "epidural abscess", "surgical site infection",
            "spondylodiscitis", "pyogenic", "tuberculosis spine",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporosis", "osteoporotic", "vertebroplasty",
            "kyphoplasty", "compression fracture",
            "osteoporotic vertebral fracture", "OVF",
            "bone mineral density", "DEXA", "DXA",
            "fragility fracture",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical", "ACDF", "cervical disc",
            "cervical myelopathy", "cervical radiculopathy",
            "anterior cervical", "posterior cervical",
            "cervical laminoplasty", "cervical arthroplasty",
            "C-spine", "atlantoaxial", "odontoid",
            "subaxial", "cervical spondylotic",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar", "TLIF", "PLIF", "ALIF", "OLIF", "XLIF",
            "lumbar fusion", "lumbar stenosis",
            "lumbar disc", "lumbar spondylolisthesis",
            "interbody fusion", "posterolateral fusion",
            "lumbar decompression", "cauda equina",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive", "MIS", "MISS",
            "mini-open", "percutaneous",
            "tubular retractor", "MIS-TLIF",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic", "endoscopy",
            "biportal endoscopic", "UBE",
            "unilateral biportal endoscopic",
            "full endoscopic", "percutaneous endoscopic",
            "transforaminal endoscopic",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation", "robot", "robotic",
            "augmented reality", "computer-assisted",
            "robot-assisted", "O-arm", "intraoperative CT",
            "3D navigation",
        ],
    },
    "Complications": {
        "keywords": [
            "complication", "reoperation", "revision",
            "adverse event", "adjacent segment",
            "pseudarthrosis", "nonunion", "hardware failure",
            "screw misplacement", "dural tear",
            "CSF leak", "wound dehiscence",
        ],
    },
    "Outcomes": {
        "keywords": [
            "outcome", "quality of life", "disability",
            "ODI", "Oswestry", "VAS", "SF-36", "SF-12",
            "patient-reported outcome", "PROM", "EQ-5D",
            "JOA score", "Nurick", "mJOA",
            "functional outcome", "satisfaction",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics", "biomechanical",
            "finite element", "cadaveric",
            "load", "stiffness", "range of motion",
            "pullout strength", "fatigue testing",
            "mechanical testing", "stress distribution",
        ],
    },
}


# ── Scored article result ─────────────────────────────────────────────

@dataclass
class SpineScoredArticle:
    """Scoring result for a spine paper."""
    paper: Paper
    interest_areas: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    is_starred: bool = False
    title_ja: str = ""
    summary_ja: str = ""

    @property
    def all_topics(self) -> list[str]:
        return sorted(set(self.interest_areas + self.general_topics))

    @property
    def star_label(self) -> str:
        return "★" if self.is_starred else ""


# ── Scorer ────────────────────────────────────────────────────────────

def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:

    def score_paper(self, paper: Paper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for area_name, profile in INTEREST_AREA_PROFILES.items():
            if self._matches_interest_area(full_text, paper.title, profile):
                result.interest_areas.append(area_name)

        for topic_name, profile in GENERAL_TOPIC_PROFILES.items():
            if self._matches_general_topic(full_text, profile):
                result.general_topics.append(topic_name)

        result.is_starred = len(result.interest_areas) > 0
        return result

    def _matches_interest_area(self, full_text: str, title: str, profile: dict) -> bool:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                score += 0.4 if _text_contains(title, term) else 0.3
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                score += 0.2 if _text_contains(title, term) else 0.15
        for term in profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.05
        return score >= 0.15

    def _matches_general_topic(self, full_text: str, profile: dict) -> bool:
        for kw in profile.get("keywords", []):
            if _text_contains(full_text, kw):
                return True
        return False

    def score_and_classify(self, papers: list[Paper]) -> list[SpineScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]
        result = starred + unstarred
        n_starred = len(starred)
        logger.info(f"Scored {len(scored)} papers: {n_starred} starred, {len(unstarred)} unstarred")
        return result
