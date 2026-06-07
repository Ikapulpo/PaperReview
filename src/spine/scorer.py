"""Interest-area scoring for spine papers.

Marks papers matching the user's 4 interest areas with ★,
and classifies papers into general spine topics for the Notion database.
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)


STAR_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence",
            "machine learning",
            "deep learning",
            "neural network",
            "natural language processing",
            "large language model",
            "ChatGPT",
            "GPT-4",
            "computer vision",
            "convolutional neural network",
            "random forest",
            "gradient boosting",
            "XGBoost",
            "support vector machine",
            "radiomics",
            "generative AI",
        ],
        "secondary": [
            "classification model",
            "prediction model",
            "predictive model",
            "image recognition",
            "segmentation model",
            "detection model",
            "transformer model",
            "BERT",
            "automated detection",
            "automated classification",
            "automated measurement",
            "automated segmentation",
        ],
        "context": [
            "model performance",
            "AUC",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication",
            "patient selection",
            "operative indication",
            "surgical decision",
            "decision-making",
            "conservative versus surgical",
            "conservative vs surgical",
            "operative versus conservative",
            "operative vs conservative",
            "surgical candidacy",
            "appropriate use criteria",
            "indication for surgery",
        ],
        "secondary": [
            "shared decision",
            "treatment selection",
            "clinical pathway",
            "optimal timing",
            "risk stratification",
            "cost-effectiveness",
            "QALY",
            "value-based care",
        ],
        "context": [
            "selection criteria",
            "preoperative assessment",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc",
            "nucleus pulposus",
            "annulus fibrosus",
            "disc degeneration",
            "disc regeneration",
            "endplate",
            "cartilaginous endplate",
            "dorsal root ganglion",
            "nerve root",
            "spinal cord injury",
            "neuropathic pain",
            "bone metabolism",
            "bone remodeling",
            "osteoclast",
            "osteoblast",
            "osteocyte",
            "RANKL",
            "OPG",
            "osteoprotegerin",
            "bone immunology",
            "osteoimmunology",
        ],
        "secondary": [
            "in vitro",
            "in vivo",
            "cell culture",
            "animal model",
            "mouse model",
            "rat model",
            "rabbit model",
            "stem cell",
            "mesenchymal stem cell",
            "MSC",
            "chondrocyte",
            "notochordal cell",
            "inflammatory cytokine",
            "TNF-α",
            "IL-1β",
            "IL-6",
            "NF-κB",
            "Wnt signaling",
            "BMP",
            "TGF-β",
            "gene expression",
            "signaling pathway",
            "extracellular matrix",
            "collagen",
            "proteoglycan",
            "aggrecan",
            "matrix metalloproteinase",
            "MMP",
            "apoptosis",
            "autophagy",
            "senescence",
            "oxidative stress",
            "mechanobiology",
            "mechanotransduction",
        ],
        "context": [
            "pathogenesis",
            "molecular mechanism",
            "biological",
            "histological",
            "immunohistochemistry",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial",
            "scaffold",
            "hydrogel",
            "bone graft substitute",
            "bone substitute",
            "synthetic graft",
            "bioactive glass",
            "bioceramics",
            "hydroxyapatite",
            "β-TCP",
            "beta-tricalcium phosphate",
            "calcium phosphate",
            "3D printing",
            "bioprinting",
            "tissue engineering",
            "drug delivery",
            "growth factor delivery",
            "nanoparticle",
            "nanofiber",
            "electrospinning",
        ],
        "secondary": [
            "biocompatibility",
            "biodegradable",
            "bioresorbable",
            "osteoconductive",
            "osteoinductive",
            "bone ingrowth",
            "porous structure",
            "surface modification",
            "coating",
            "titanium alloy",
            "PEEK",
            "polyetheretherketone",
            "polymer",
            "composite",
            "mechanical testing",
            "degradation",
            "cytocompatibility",
            "cell adhesion",
            "cell proliferation",
            "in vitro evaluation",
            "bioactivity",
        ],
        "context": [
            "implant material",
            "cage material",
            "graft material",
            "material property",
        ],
    },
}

GENERAL_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative",
            "spondylosis",
            "disc degeneration",
            "disc herniation",
            "spinal stenosis",
            "spondylolisthesis",
            "foraminal stenosis",
            "adjacent segment",
        ],
    },
    "Deformity": {
        "keywords": [
            "scoliosis",
            "kyphosis",
            "lordosis",
            "deformity",
            "sagittal balance",
            "sagittal alignment",
            "coronal balance",
            "pelvic incidence",
            "spinal alignment",
            "adult spinal deformity",
            "adolescent idiopathic",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture",
            "trauma",
            "burst fracture",
            "dislocation",
            "spinal cord injury",
            "SCI",
            "whiplash",
            "traumatic",
            "vertebral fracture",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor",
            "tumour",
            "metastasis",
            "metastatic",
            "neoplasm",
            "chordoma",
            "schwannoma",
            "meningioma",
            "osteosarcoma",
            "en bloc",
            "oncology",
            "spinal cord tumor",
        ],
    },
    "Infection": {
        "keywords": [
            "infection",
            "spondylodiscitis",
            "discitis",
            "osteomyelitis",
            "epidural abscess",
            "surgical site infection",
            "SSI",
            "tuberculosis",
            "pyogenic",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporosis",
            "osteoporotic",
            "osteopenia",
            "vertebral compression fracture",
            "OVF",
            "kyphoplasty",
            "vertebroplasty",
            "bone mineral density",
            "BMD",
            "DEXA",
            "DXA",
            "fragility fracture",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical",
            "C-spine",
            "ACDF",
            "anterior cervical",
            "cervical disc",
            "cervical myelopathy",
            "cervical radiculopathy",
            "cervical laminoplasty",
            "cervical fusion",
            "atlantoaxial",
            "odontoid",
            "occipitocervical",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar",
            "L-spine",
            "PLIF",
            "TLIF",
            "XLIF",
            "OLIF",
            "ALIF",
            "lumbar fusion",
            "lumbar stenosis",
            "lumbar disc",
            "cauda equina",
            "lumbosacral",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive",
            "MIS",
            "MISS",
            "percutaneous",
            "tubular retractor",
            "mini-open",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic",
            "endoscopy",
            "full-endoscopic",
            "biportal",
            "uniportal",
            "transforaminal endoscopic",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation",
            "robotic",
            "robot-assisted",
            "computer-assisted",
            "augmented reality",
            "intraoperative CT",
            "O-arm",
            "pedicle screw accuracy",
        ],
    },
    "Complications": {
        "keywords": [
            "complication",
            "reoperation",
            "revision",
            "pseudarthrosis",
            "nonunion",
            "hardware failure",
            "dural tear",
            "CSF leak",
            "wound",
            "adverse event",
            "morbidity",
        ],
    },
    "Outcomes": {
        "keywords": [
            "outcome",
            "follow-up",
            "long-term result",
            "patient satisfaction",
            "VAS",
            "ODI",
            "JOA",
            "NDI",
            "SF-36",
            "EQ-5D",
            "return to work",
            "functional outcome",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics",
            "biomechanical",
            "finite element",
            "FEA",
            "cadaver",
            "cadaveric",
            "range of motion",
            "ROM",
            "load sharing",
            "stiffness",
            "stress distribution",
            "kinematics",
        ],
    },
}


@dataclass
class SpineScoredArticle:
    """Scoring result for a spine paper."""

    paper: SpinePaper
    star_topics: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    star_score: float = 0.0

    @property
    def is_starred(self) -> bool:
        return len(self.star_topics) > 0

    @property
    def all_topics(self) -> list[str]:
        return self.star_topics + self.general_topics


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


TITLE_MULTIPLIER = 2.0
STAR_THRESHOLD = 0.30


class SpineScorer:

    def score_paper(self, paper: SpinePaper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        best_star_score = 0.0
        for topic_name, profile in STAR_PROFILES.items():
            score = self._score_star_topic(paper, full_text, profile)
            if score >= STAR_THRESHOLD:
                result.star_topics.append(topic_name)
                best_star_score = max(best_star_score, score)
        result.star_score = best_star_score

        for topic_name, profile in GENERAL_PROFILES.items():
            if self._matches_general_topic(full_text, profile):
                result.general_topics.append(topic_name)

        return result

    def _score_star_topic(
        self, paper: SpinePaper, full_text: str, profile: dict
    ) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = (
                    TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                )
                score += 0.3 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = (
                    TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                )
                score += 0.15 * mult
        for term in profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.05
        return min(score, 1.0)

    def _matches_general_topic(self, full_text: str, profile: dict) -> bool:
        matches = sum(
            1 for kw in profile["keywords"] if _text_contains(full_text, kw)
        )
        return matches >= 2

    def score_and_rank(
        self, papers: list[SpinePaper]
    ) -> list[SpineScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]
        starred.sort(key=lambda x: x.star_score, reverse=True)
        result = starred + unstarred
        star_count = len(starred)
        logger.info(
            f"Scored {len(scored)} papers: {star_count} starred, "
            f"{len(unstarred)} unstarred"
        )
        return result
