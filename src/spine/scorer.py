"""Relevance scoring engine for spine journal papers.

Classifies papers into general spine topics and identifies papers matching
the user's 4 interest areas (marked with ★):
  ★ 脊椎外科とAI
  ★ 脊椎外科手術の適応評価
  ★ 脊椎の基礎研究
  ★ バイオマテリアル

General topics (no ★):
  Degenerative, Deformity, Trauma, Tumor, Infection, OVF/Osteoporosis,
  Cervical, Lumbar, Minimally invasive, Endoscopic, Navigation/Robotics,
  Complications, Outcomes, Biomechanics
"""

import logging
import re
from dataclasses import dataclass, field

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)

# ── Interest area profiles (★) ────────────────────────────────────────────

INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "convolutional neural network",
            "natural language processing", "large language model",
            "ChatGPT", "GPT-4", "GPT-3",
            "computer vision", "image recognition",
            "automated diagnosis", "automated detection",
            "clinical decision support",
        ],
        "secondary": [
            "random forest", "gradient boosting", "XGBoost",
            "support vector machine", "logistic regression",
            "radiomics", "predictive model", "prediction model",
            "CNN", "NLP", "LLM", "transformer",
            "algorithm", "classifier", "classification model",
            "segmentation model", "detection model",
        ],
        "context": [
            "AI", "automation", "computational",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "patient selection",
            "treatment decision", "surgical decision",
            "decision making", "shared decision",
            "appropriateness criteria",
            "operative vs nonoperative", "conservative vs operative",
            "conservative vs surgical",
        ],
        "secondary": [
            "outcome prediction", "prognostic factor", "predictive factor",
            "risk stratification", "cost-effectiveness", "QALY",
            "clinical prediction rule", "treatment outcome",
            "risk-benefit", "treatment selection",
            "surgical planning", "indication",
        ],
        "context": [
            "patient preference", "value-based",
            "outcome", "prognosis",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "nucleus pulposus", "annulus fibrosus",
            "cartilage endplate", "disc degeneration",
            "dorsal root ganglion", "DRG", "nerve root",
            "spinal cord injury",
            "osteoclast", "osteoblast", "osteocyte",
            "bone metabolism", "bone remodeling",
            "RANKL", "osteoprotegerin",
        ],
        "secondary": [
            "stem cell", "mesenchymal stem cell", "iPSC",
            "cell culture", "in vitro", "in vivo",
            "animal model", "rat model", "mouse model",
            "inflammatory mediator", "cytokine",
            "TNF", "interleukin", "IL-1", "IL-6",
            "neuropathic pain", "nociceptor",
            "Wnt signaling", "BMP", "TGF-beta",
            "notochord", "extracellular matrix",
            "proteoglycan", "collagen",
            "apoptosis", "senescence", "autophagy",
            "gene expression", "signaling pathway",
        ],
        "context": [
            "molecular", "cellular", "tissue engineering",
            "regeneration", "pathogenesis", "mechanism",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "scaffold", "hydrogel",
            "bone graft substitute", "bone substitute",
            "tissue engineering", "biocompatibility",
            "3D printing", "additive manufacturing",
            "bioprinting",
        ],
        "secondary": [
            "hydroxyapatite", "calcium phosphate", "beta-TCP",
            "β-TCP", "ceramic", "titanium alloy",
            "PEEK", "polyether ether ketone",
            "bone morphogenetic protein", "rhBMP",
            "growth factor", "biodegradable", "bioresorbable",
            "polymer", "composite", "coating",
            "interbody cage", "porous",
            "surface modification", "osseointegration",
            "drug delivery", "controlled release",
        ],
        "context": [
            "implant", "graft", "material",
            "mechanical property", "bioactive",
        ],
    },
}

# ── General spine topic profiles ───────────────────────────────────────────

GENERAL_TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "primary": [
            "degenerative", "spondylosis", "disc herniation",
            "spinal stenosis", "canal stenosis",
            "radiculopathy", "myelopathy",
            "degenerative disc disease",
        ],
        "secondary": [
            "herniated disc", "bulging disc", "foraminal stenosis",
            "neurogenic claudication",
        ],
    },
    "Deformity": {
        "primary": [
            "scoliosis", "kyphosis", "lordosis",
            "sagittal balance", "sagittal alignment",
            "adult spinal deformity", "adolescent idiopathic scoliosis",
            "spinal deformity",
        ],
        "secondary": [
            "pelvic incidence", "coronal balance", "SVA",
            "Cobb angle", "congenital scoliosis",
            "sagittal vertical axis", "global alignment",
            "pelvic tilt", "sacral slope",
        ],
    },
    "Trauma": {
        "primary": [
            "fracture", "burst fracture", "dislocation",
            "spinal cord injury", "SCI", "trauma",
        ],
        "secondary": [
            "traumatic", "polytrauma", "flexion-distraction",
            "chance fracture", "hangman", "Jefferson",
        ],
    },
    "Tumor": {
        "primary": [
            "tumor", "metastasis", "metastatic",
            "primary spine tumor", "neoplasm",
        ],
        "secondary": [
            "schwannoma", "meningioma", "chordoma",
            "osteosarcoma", "Ewing", "en bloc",
            "oncology", "intradural", "extramedullary",
        ],
    },
    "Infection": {
        "primary": [
            "spondylodiscitis", "discitis", "osteomyelitis",
            "spinal infection", "epidural abscess",
        ],
        "secondary": [
            "pyogenic", "tuberculosis", "tuberculous",
            "postoperative infection", "surgical site infection",
        ],
    },
    "OVF/Osteoporosis": {
        "primary": [
            "osteoporosis", "osteoporotic", "vertebral fracture",
            "compression fracture", "OVF", "OVCF",
            "vertebroplasty", "kyphoplasty",
        ],
        "secondary": [
            "bone cement", "PMMA", "insufficiency fracture",
            "bone mineral density", "balloon kyphoplasty",
            "osteopenia",
        ],
    },
    "Cervical": {
        "primary": [
            "cervical spine", "cervical disc",
            "cervical myelopathy", "cervical radiculopathy",
            "ACDF", "cervical laminoplasty",
        ],
        "secondary": [
            "anterior cervical", "posterior cervical",
            "atlas", "axis", "odontoid", "C1-C2",
            "subaxial", "cervical spondylosis",
        ],
    },
    "Lumbar": {
        "primary": [
            "lumbar spine", "lumbar stenosis", "lumbar disc",
            "lumbar fusion", "lumbar decompression",
        ],
        "secondary": [
            "TLIF", "PLIF", "ALIF", "XLIF", "OLIF",
            "transforaminal", "cauda equina",
            "lumbar spondylosis",
        ],
    },
    "Minimally invasive": {
        "primary": [
            "minimally invasive", "MIS spine", "MISS",
            "percutaneous fixation",
        ],
        "secondary": [
            "tubular retractor", "mini-open",
            "percutaneous pedicle screw",
        ],
    },
    "Endoscopic": {
        "primary": [
            "endoscopic spine", "full-endoscopic",
            "biportal endoscopic", "uniportal endoscopic",
        ],
        "secondary": [
            "endoscopy", "endoscopic discectomy",
            "endoscopic decompression",
        ],
    },
    "Navigation/Robotics": {
        "primary": [
            "navigation", "robotic", "robot-assisted",
            "computer-assisted surgery",
        ],
        "secondary": [
            "O-arm", "CT navigation", "augmented reality",
            "intraoperative imaging", "3D navigation",
        ],
    },
    "Complications": {
        "primary": [
            "complication", "reoperation", "revision surgery",
            "adjacent segment disease",
        ],
        "secondary": [
            "pseudarthrosis", "nonunion", "implant failure",
            "dural tear", "CSF leak", "neurological deficit",
            "hardware failure", "rod fracture",
        ],
    },
    "Outcomes": {
        "primary": [
            "patient-reported outcome", "PROM",
            "clinical outcome", "functional outcome",
        ],
        "secondary": [
            "VAS", "ODI", "NDI", "JOA score",
            "SF-36", "EQ-5D", "quality of life",
            "return to work", "satisfaction",
        ],
    },
    "Biomechanics": {
        "primary": [
            "biomechanics", "biomechanical",
            "finite element", "FEA",
        ],
        "secondary": [
            "cadaveric", "range of motion", "ROM",
            "stiffness", "pullout strength", "load",
            "stress analysis", "strain",
        ],
    },
}


# ── Scored article result ──────────────────────────────────────────────

@dataclass
class SpineScoredArticle:
    """Scoring result for a spine paper."""
    paper: SpinePaper
    interest_topics: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    interest_scores: dict[str, float] = field(default_factory=dict)
    general_scores: dict[str, float] = field(default_factory=dict)

    @property
    def is_starred(self) -> bool:
        return len(self.interest_topics) > 0

    @property
    def all_topics(self) -> list[str]:
        return self.interest_topics + self.general_topics

    @property
    def best_interest_score(self) -> float:
        return max(self.interest_scores.values()) if self.interest_scores else 0.0


# ── Scorer ─────────────────────────────────────────────────────────────

def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: SpinePaper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineRelevanceScorer:

    TITLE_MULTIPLIER = 2.0
    INTEREST_THRESHOLD = 0.15
    GENERAL_THRESHOLD = 0.10

    def score_paper(self, paper: SpinePaper) -> SpineScoredArticle:
        result = SpineScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        # Score interest areas (★)
        for topic_name, profile in INTEREST_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.interest_scores[topic_name] = score
            if score >= self.INTEREST_THRESHOLD:
                result.interest_topics.append(topic_name)

        # Score general topics
        for topic_name, profile in GENERAL_TOPIC_PROFILES.items():
            score = self._score_general_topic(paper, full_text, profile)
            result.general_scores[topic_name] = score
            if score >= self.GENERAL_THRESHOLD:
                result.general_topics.append(topic_name)

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
                score += 0.15 * mult
        for term in profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.05
        return min(score, 1.0)

    def _score_general_topic(self, paper: SpinePaper, full_text: str, profile: dict) -> float:
        score = 0.0
        for term in profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.25 * mult
        for term in profile.get("secondary", []):
            if _text_contains(full_text, term):
                score += 0.10
        return min(score, 1.0)

    def score_and_rank(self, papers: list[SpinePaper]) -> list[SpineScoredArticle]:
        """Score all papers and return sorted: ★ first, then non-★."""
        scored = [self.score_paper(p) for p in papers]

        starred = [s for s in scored if s.is_starred]
        non_starred = [s for s in scored if not s.is_starred]

        # Sort within each group by interest score (starred) or general score (non-starred)
        starred.sort(key=lambda x: x.best_interest_score, reverse=True)
        non_starred.sort(
            key=lambda x: max(x.general_scores.values()) if x.general_scores else 0,
            reverse=True,
        )

        result = starred + non_starred
        if result:
            logger.info(
                f"Scored {len(result)} papers: "
                f"{len(starred)} ★ (interest), {len(non_starred)} general"
            )
        return result
