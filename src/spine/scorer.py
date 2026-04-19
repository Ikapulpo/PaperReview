"""Interest-area scorer for spine papers.

Marks papers matching the user's 4 interest areas with ★:
  1. 脊椎外科とAI
  2. 脊椎外科手術の適応評価
  3. 脊椎の基礎研究（椎間板組織や神経組織、骨免疫・骨代謝など）
  4. バイオマテリアルの基礎・または臨床評価

Also assigns general spine topics for Notion multi_select.
"""

import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper


INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning",
            "deep learning", "neural network",
            "convolutional neural network", "CNN",
            "natural language processing", "NLP",
            "large language model", "LLM",
            "ChatGPT", "GPT-4", "GPT-3",
            "computer vision", "image recognition",
            "automated detection", "automated classification",
            "predictive model", "prediction model",
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "SVM",
            "transformer model",
        ],
        "secondary": [
            "algorithm", "computational",
            "data-driven", "data driven",
            "classification model", "regression model",
            "feature extraction", "segmentation",
            "radiomics", "imaging analysis",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "patient selection",
            "treatment decision", "clinical decision",
            "shared decision", "decision-making",
            "operative vs conservative",
            "conservative vs surgical",
            "nonoperative vs operative",
            "surgical candidacy", "appropriateness criteria",
            "treatment algorithm",
            "outcome prediction", "prognostic factor",
            "risk stratification", "preoperative assessment",
        ],
        "secondary": [
            "cost-effectiveness", "cost effectiveness",
            "cost-utility", "QALY",
            "value-based", "shared decision making",
            "patient-reported outcome", "PRO",
            "minimal clinically important difference", "MCID",
            "treatment threshold", "indication criteria",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "disc degeneration",
            "nucleus pulposus", "annulus fibrosus",
            "notochordal cell", "disc cell",
            "spinal cord injury", "spinal cord regeneration",
            "dorsal root ganglion", "DRG",
            "nerve root", "neuropathic pain",
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "osteoprotegerin", "OPG",
            "osteoimmunology", "bone immunology",
            "Wnt signaling", "BMP signaling",
            "mesenchymal stem cell", "MSC",
            "chondrocyte", "cartilage endplate",
            "in vitro", "in vivo", "animal model",
            "rat model", "mouse model", "rabbit model",
        ],
        "secondary": [
            "cell culture", "tissue engineering",
            "gene expression", "signaling pathway",
            "inflammation pathway", "cytokine",
            "extracellular matrix", "proteoglycan",
            "collagen", "aggrecan", "matrix metalloproteinase",
            "apoptosis", "autophagy", "senescence",
            "oxidative stress", "hypoxia",
            "stem cell", "progenitor cell",
            "growth factor", "differentiation",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "bio-material",
            "scaffold", "bone graft",
            "bone substitute", "bone graft substitute",
            "hydroxyapatite", "calcium phosphate",
            "tricalcium phosphate", "TCP",
            "beta-TCP", "β-TCP",
            "PEEK", "polyetheretherketone",
            "titanium alloy", "titanium implant",
            "3D printing", "3D-printed",
            "additive manufacturing",
            "biocompatible", "biocompatibility",
            "bioresorbable", "biodegradable",
            "bone cement", "PMMA",
            "interbody cage", "cage subsidence",
            "porous structure", "surface coating",
            "osseointegration",
        ],
        "secondary": [
            "implant design", "implant surface",
            "bioactive", "bioactive glass",
            "ceramic", "composite material",
            "drug delivery", "growth factor delivery",
            "mechanical property", "biomechanical testing",
            "coating", "surface modification",
            "corrosion", "wear debris",
        ],
    },
}

GENERAL_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Degenerative": [
        "degenerative", "spondylosis", "stenosis", "disc herniation",
        "disc disease", "spondylolisthesis", "radiculopathy", "myelopathy",
    ],
    "Deformity": [
        "scoliosis", "kyphosis", "deformity", "sagittal balance",
        "sagittal alignment", "coronal balance", "spinal alignment",
        "adult spinal deformity", "adolescent idiopathic",
    ],
    "Trauma": [
        "fracture", "trauma", "burst fracture", "dislocation",
        "spinal injury", "vertebral fracture", "thoracolumbar fracture",
    ],
    "Tumor": [
        "tumor", "tumour", "metastasis", "metastatic", "neoplasm",
        "spinal tumor", "intradural", "extradural", "chordoma",
    ],
    "Infection": [
        "infection", "spondylodiscitis", "osteomyelitis",
        "epidural abscess", "surgical site infection", "SSI",
    ],
    "OVF/Osteoporosis": [
        "osteoporosis", "osteoporotic", "vertebral compression fracture",
        "OVF", "OVCF", "kyphoplasty", "vertebroplasty",
        "bone mineral density", "BMD", "DEXA",
    ],
    "Cervical": [
        "cervical", "ACDF", "cervical disc", "cervical myelopathy",
        "cervical stenosis", "anterior cervical", "posterior cervical",
        "cervical laminoplasty", "cervical arthroplasty",
    ],
    "Lumbar": [
        "lumbar", "PLIF", "TLIF", "XLIF", "OLIF", "ALIF",
        "lumbar fusion", "lumbar stenosis", "lumbar disc",
        "lumbar decompression", "cauda equina",
    ],
    "Minimally invasive": [
        "minimally invasive", "MIS", "mini-open",
        "percutaneous", "tubular retractor",
    ],
    "Endoscopic": [
        "endoscopic", "full-endoscopic", "biportal endoscopic",
        "uniportal endoscopic", "endoscopy",
    ],
    "Navigation/Robotics": [
        "navigation", "robotic", "robot-assisted",
        "computer-assisted", "augmented reality", "mixed reality",
        "intraoperative CT", "O-arm", "stereotactic",
    ],
    "Complications": [
        "complication", "reoperation", "revision surgery",
        "adjacent segment", "pseudarthrosis", "nonunion",
        "dural tear", "CSF leak", "neurological deficit",
        "hardware failure", "screw loosening",
    ],
    "Outcomes": [
        "outcome", "follow-up", "long-term result",
        "patient satisfaction", "return to work",
        "ODI", "Oswestry", "VAS", "JOA", "SF-36", "EQ-5D",
        "functional outcome", "clinical outcome",
    ],
    "Biomechanics": [
        "biomechanics", "biomechanical", "finite element",
        "range of motion", "ROM", "load bearing",
        "stress distribution", "strain", "stiffness",
        "cadaveric", "cadaver study",
    ],
}


@dataclass
class SpineScoredArticle:
    paper: Paper
    interest_areas: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    is_starred: bool = False
    title_ja: str = ""
    summary_ja: str = ""

    @property
    def all_topics(self) -> list[str]:
        return self.interest_areas + self.general_topics


def _text_contains(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    if len(keyword) <= 5 and keyword.isalpha():
        escaped = rf"\b{escaped}\b"
    return bool(re.search(escaped, text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineInterestScorer:

    def score_paper(self, paper: Paper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for area_name, profile in INTEREST_PROFILES.items():
            if self._matches_area(paper, full_text, profile):
                result.interest_areas.append(area_name)

        result.is_starred = len(result.interest_areas) > 0

        for topic_name, keywords in GENERAL_TOPIC_KEYWORDS.items():
            for kw in keywords:
                if _text_contains(full_text, kw):
                    result.general_topics.append(topic_name)
                    break

        return result

    def _matches_area(self, paper: Paper, full_text: str, profile: dict) -> bool:
        primary_hits = sum(
            1 for term in profile.get("primary", [])
            if _text_contains(full_text, term)
        )
        secondary_hits = sum(
            1 for term in profile.get("secondary", [])
            if _text_contains(full_text, term)
        )
        title_boost = any(
            _text_contains(paper.title, term)
            for term in profile.get("primary", [])
        )
        if title_boost:
            return True
        if primary_hits >= 2:
            return True
        if primary_hits >= 1 and secondary_hits >= 1:
            return True
        return False

    def score_all(self, papers: list[Paper]) -> list[SpineScoredArticle]:
        return [self.score_paper(p) for p in papers]

    def partition(
        self, scored: list[SpineScoredArticle],
    ) -> tuple[list[SpineScoredArticle], list[SpineScoredArticle]]:
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]
        return starred, unstarred
