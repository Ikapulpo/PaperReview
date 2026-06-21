"""Spine paper scorer: assigns ★ for interest areas and classifies general topics."""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)

# ── ★ Interest area profiles (papers matching these get ★) ──────────────

STAR_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning",
            "deep learning", "neural network", "convolutional neural",
            "natural language processing", "large language model",
            "ChatGPT", "GPT-4", "GPT-3", "computer vision",
            "automated detection", "automated classification",
            "automated segmentation", "image recognition",
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "logistic regression model",
            "radiomics",
        ],
        "secondary": [
            "prediction model", "predictive model",
            "predictive algorithm", "classification algorithm",
            "transfer learning", "federated learning",
            "clinical decision support", "decision support system",
            "segmentation model", "object detection model",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "patient selection",
            "treatment decision", "operative criteria",
            "surgical candidacy", "decision-making",
            "appropriateness criteria", "surgical threshold",
            "conservative versus operative",
            "conservative versus surgical",
            "conservative vs surgical", "conservative vs operative",
            "nonoperative versus operative",
            "surgical timing", "optimal timing for surgery",
            "shared decision",
        ],
        "secondary": [
            "treatment algorithm", "clinical prediction rule",
            "appropriateness score",
            "cost-effectiveness analysis", "utility analysis",
            "minimal clinically important difference",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "disc degeneration",
            "nucleus pulposus", "annulus fibrosus",
            "endplate cartilage", "notochordal cell",
            "spinal cord injury model", "nerve root injury",
            "dorsal root ganglion", "neuropathic pain model",
            "neuroinflammation", "neuroregeneration",
            "osteoclast differentiation", "osteoblast differentiation",
            "osteocyte", "osteoimmunology",
            "stem cell therapy", "mesenchymal stem cell",
            "cell therapy", "gene therapy",
            "in vitro", "in vivo", "animal model",
            "rat model", "mouse model", "rabbit model",
        ],
        "secondary": [
            "disc cell", "chondrocyte differentiation",
            "extracellular matrix", "proteoglycan",
            "inflammatory cytokine", "TNF-alpha", "NF-kB",
            "Wnt signaling", "BMP signaling", "TGF-beta",
            "apoptosis", "senescence", "autophagy",
            "oxidative stress", "mechanotransduction",
            "spinal cord regeneration", "axonal regeneration",
            "demyelination", "remyelination",
            "bone remodeling", "bone metabolism",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "scaffold", "hydrogel",
            "tissue engineering", "bone graft substitute",
            "ceramic implant", "hydroxyapatite",
            "tricalcium phosphate", "bone cement",
            "3D printing", "3D-printed", "bioprinting",
            "additive manufacturing",
            "bioactive glass", "porous implant",
            "surface modification", "surface coating",
        ],
        "secondary": [
            "osseointegration",
            "drug delivery system", "controlled release",
            "nanoparticle", "nanofiber",
            "collagen scaffold", "fibrin scaffold",
            "cell-seeded", "growth factor delivery",
            "bone substitute", "synthetic bone graft",
            "demineralized bone matrix",
        ],
    },
}

# ── General topic profiles (for Notion Topics classification) ───────────

GENERAL_TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative", "spondylosis", "spinal stenosis",
            "disc herniation", "herniated disc",
            "radiculopathy", "myelopathy", "claudication",
            "spondylolisthesis", "foraminal stenosis",
            "central stenosis", "lateral recess",
        ],
    },
    "Deformity": {
        "keywords": [
            "deformity", "scoliosis", "kyphosis",
            "sagittal balance", "sagittal alignment",
            "coronal balance", "spinal alignment",
            "pelvic incidence", "pelvic tilt",
            "lumbar lordosis", "thoracic kyphosis",
            "adult spinal deformity",
            "adolescent idiopathic scoliosis",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture", "trauma", "burst fracture",
            "compression fracture", "dislocation",
            "traumatic", "vertebral body fracture",
            "chance fracture", "hangman",
            "odontoid fracture", "atlas fracture",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor", "tumour", "metastasis", "metastatic",
            "neoplasm", "malignancy", "oncology",
            "chordoma", "osteosarcoma", "schwannoma",
            "meningioma", "ependymoma",
            "primary bone tumor", "intradural",
        ],
    },
    "Infection": {
        "keywords": [
            "infection", "spondylodiscitis", "discitis",
            "osteomyelitis", "epidural abscess",
            "surgical site infection",
            "postoperative infection", "pyogenic",
            "tuberculous spondylitis", "spinal tuberculosis",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporosis", "osteoporotic",
            "osteoporotic vertebral fracture",
            "vertebral compression fracture",
            "vertebroplasty", "kyphoplasty",
            "bone cement augmentation",
            "fragility fracture",
            "bone density",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical spine", "cervical myelopathy",
            "cervical disc", "anterior cervical",
            "cervical laminoplasty", "cervical arthroplasty",
            "cervical fusion", "atlantoaxial",
            "occipitocervical", "subaxial cervical",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar spine", "lumbar fusion",
            "lumbar stenosis", "lumbar disc",
            "lumbar discectomy", "lumbosacral",
            "cauda equina",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive", "percutaneous pedicle",
            "tubular retractor", "mini-open",
            "muscle-sparing",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic", "full-endoscopic",
            "biportal endoscopic", "uniportal endoscopic",
            "transforaminal endoscopic",
            "interlaminar endoscopic",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation system", "robotic surgery",
            "robotic-assisted", "computer-assisted surgery",
            "image-guided surgery", "augmented reality",
            "intraoperative navigation",
            "pedicle screw accuracy",
        ],
    },
    "Complications": {
        "keywords": [
            "complication", "revision surgery",
            "reoperation", "adjacent segment disease",
            "pseudarthrosis", "nonunion",
            "hardware failure", "implant failure",
            "dural tear", "wound complication",
        ],
    },
    "Outcomes": {
        "keywords": [
            "patient-reported outcome",
            "quality of life", "functional outcome",
            "long-term outcome", "return to work",
            "clinical outcome",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics", "biomechanical",
            "finite element", "range of motion",
            "cadaveric study", "cadaver study",
            "motion segment", "pullout strength",
            "mechanical testing",
        ],
    },
}


@dataclass
class SpineScoredArticle:
    paper: Paper
    is_star: bool = False
    star_topics: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    star_score: float = 0.0
    title_ja: str = ""
    summary_ja: str = ""


def _text_contains(text: str, keyword: str) -> bool:
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:

    STAR_THRESHOLD = 0.20

    def score_paper(self, paper: Paper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for topic_name, profile in STAR_PROFILES.items():
            score = self._score_star_topic(paper, full_text, profile)
            if score >= self.STAR_THRESHOLD:
                result.is_star = True
                result.star_topics.append(topic_name)
                result.star_score = max(result.star_score, score)

        for topic_name, profile in GENERAL_TOPIC_PROFILES.items():
            if self._matches_general_topic(full_text, profile):
                result.general_topics.append(topic_name)

        return result

    def _score_star_topic(self, paper: Paper, full_text: str, profile: dict) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = 2.0 if _text_contains(paper.title, term) else 1.0
                score += 0.3 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = 2.0 if _text_contains(paper.title, term) else 1.0
                score += 0.15 * mult
        return min(score, 1.0)

    def _matches_general_topic(self, full_text: str, profile: dict) -> bool:
        matches = sum(
            1 for kw in profile.get("keywords", [])
            if _text_contains(full_text, kw)
        )
        return matches >= 2

    def score_and_rank(self, papers: list[Paper]) -> list[SpineScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        starred = sorted(
            [s for s in scored if s.is_star],
            key=lambda x: x.star_score, reverse=True,
        )
        non_starred = [s for s in scored if not s.is_star]
        result = starred + non_starred
        star_count = len(starred)
        logger.info(
            f"Scored {len(scored)} papers: {star_count} ★, "
            f"{len(non_starred)} general"
        )
        return result
