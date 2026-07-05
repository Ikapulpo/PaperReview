"""Relevance scoring engine for spine surgery papers.

Classifies papers into:
  - ★ Interest areas (user's core research interests)
  - General topics (Notion database Topics property)

★ Interest areas:
  脊椎外科とAI, 脊椎外科手術の適応評価, 脊椎の基礎研究, バイオマテリアル

General topics:
  Degenerative, Deformity, Trauma, Tumor, Infection, OVF/Osteoporosis,
  Cervical, Lumbar, Minimally invasive, Endoscopic, Navigation/Robotics,
  Complications, Outcomes, Biomechanics
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "artificial intelligence", "machine learning", "deep learning",
            "neural network", "natural language processing",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "convolutional neural network",
            "random forest", "gradient boosting",
            "AI-assisted", "AI-based", "AI-driven",
            "automated detection", "automated segmentation",
            "predictive model", "prediction model",
        ],
        "secondary": [
            "radiomics", "automated", "algorithm",
            "classification model", "regression model",
            "support vector machine", "XGBoost",
            "transformer", "BERT", "generative AI",
            "image recognition", "object detection",
            "clinical decision support",
            "robotic surgery", "robot-assisted",
        ],
        "context": [
            "spine", "spinal", "vertebral",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "treatment decision",
            "patient selection", "surgical candidacy",
            "MCID", "minimal clinically important difference",
            "SCB", "substantial clinical benefit",
            "PASS", "patient acceptable symptom state",
            "operative vs nonoperative", "operative versus nonoperative",
            "surgical vs conservative", "surgical versus conservative",
            "decompression alone vs fusion",
            "decompression versus fusion",
        ],
        "secondary": [
            "patient-reported outcome", "PRO", "PROM",
            "outcome prediction", "prognostic factor",
            "risk stratification", "shared decision",
            "clinical outcome", "functional outcome",
            "cost-effectiveness", "value-based",
            "treatment algorithm", "clinical guideline",
            "comparative effectiveness",
            "symptom duration", "timing of surgery",
            "preoperative optimization",
        ],
        "context": [
            "spine surgery", "spinal surgery",
            "indication", "selection",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc", "nucleus pulposus",
            "annulus fibrosus", "disc degeneration",
            "disc regeneration", "disc repair",
            "spinal cord injury", "nerve root",
            "dorsal root ganglion", "DRG",
            "neuropathic pain", "radiculopathy",
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "osteoprotegerin",
            "bone immunology", "osteoimmunology",
        ],
        "secondary": [
            "notochordal cell", "chondrocyte",
            "mesenchymal stem cell", "MSC",
            "extracellular matrix", "collagen",
            "proteoglycan", "aggrecan",
            "inflammatory cytokine", "TNF-α", "IL-1β", "IL-6",
            "growth factor", "BMP", "TGF-β",
            "Wnt signaling", "Hedgehog signaling",
            "apoptosis", "senescence", "autophagy",
            "oxidative stress", "hypoxia",
            "animal model", "in vitro", "in vivo",
            "cell culture", "organ culture",
            "gene expression", "epigenetic",
            "mechanobiology", "mechanotransduction",
        ],
        "context": [
            "disc", "vertebral", "spinal cord",
            "neural", "bone", "cartilage",
            "basic research", "molecular",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "scaffold", "hydrogel",
            "bone graft substitute", "bone substitute",
            "biocompatible", "biodegradable",
            "tissue engineering", "regenerative medicine",
            "3D printing", "3D-printed", "additive manufacturing",
            "bioactive glass", "bioceramics",
            "calcium phosphate", "hydroxyapatite",
        ],
        "secondary": [
            "implant material", "surface modification",
            "coating", "drug delivery",
            "nanoparticle", "nanofiber",
            "polymer", "PEEK", "titanium",
            "osseointegration", "osteoconductive",
            "osteoinductive", "bioabsorbable",
            "cage material", "interbody cage",
            "bone morphogenetic protein",
            "platelet-rich plasma", "PRP",
            "stem cell delivery",
            "controlled release",
        ],
        "context": [
            "material", "graft", "implant",
            "biocompatibility", "mechanical properties",
        ],
    },
}


TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative", "spondylosis", "stenosis",
            "disc herniation", "disc disease",
            "spondylolisthesis", "myelopathy",
            "radiculopathy", "foraminal stenosis",
            "facet arthropathy", "adjacent segment",
        ],
    },
    "Deformity": {
        "keywords": [
            "scoliosis", "kyphosis", "deformity",
            "spinal alignment", "sagittal balance",
            "coronal balance", "pelvic incidence",
            "sacral slope", "lumbar lordosis",
            "thoracic kyphosis", "SVA",
            "proximal junctional", "PJK", "PJF",
            "adult spinal deformity", "ASD",
            "adolescent idiopathic scoliosis", "AIS",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture", "trauma", "burst fracture",
            "compression fracture", "dislocation",
            "spinal cord injury", "SCI",
            "traumatic", "thoracolumbar injury",
            "cervical injury", "TLICS", "SLICS",
            "subaxial", "odontoid", "atlas",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor", "tumour", "metastasis", "metastatic",
            "neoplasm", "malignancy", "sarcoma",
            "chordoma", "schwannoma", "meningioma",
            "intradural", "extradural", "epidural",
            "spinal cord tumor", "SINS", "Tokuhashi",
            "en bloc", "oncologic",
        ],
    },
    "Infection": {
        "keywords": [
            "spondylodiscitis", "discitis", "osteomyelitis",
            "epidural abscess", "spinal infection",
            "surgical site infection", "SSI",
            "pyogenic", "tuberculous", "tuberculosis",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporosis", "osteoporotic",
            "vertebral fracture", "compression fracture",
            "OVF", "OVCF",
            "vertebroplasty", "kyphoplasty",
            "bone mineral density", "BMD",
            "DEXA", "fragility fracture",
            "cement augmentation", "PMMA",
            "sarcopenia", "frailty",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical", "ACDF", "cervical disc",
            "cervical myelopathy", "DCM",
            "laminoplasty", "corpectomy",
            "cervical arthroplasty", "CDR",
            "ossification of posterior longitudinal ligament",
            "OPLL", "atlantoaxial", "occipitocervical",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar", "TLIF", "PLIF", "XLIF", "OLIF", "ALIF",
            "lumbar fusion", "lumbar stenosis",
            "lumbar disc", "lumbar spondylolisthesis",
            "cauda equina", "laminectomy",
            "posterolateral fusion", "interbody fusion",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive", "MIS", "MI-TLIF",
            "percutaneous", "tubular retractor",
            "muscle-sparing", "less invasive",
            "mini-open", "MIS-TLIF",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic", "endoscopy",
            "biportal endoscopic", "uniportal",
            "full-endoscopic", "percutaneous endoscopic",
            "PELD", "BESS", "UBE",
            "transforaminal endoscopic",
            "interlaminar endoscopic",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation", "robot", "robotic",
            "computer-assisted", "image-guided",
            "O-arm", "intraoperative CT",
            "augmented reality", "mixed reality",
            "3D navigation", "pedicle screw accuracy",
        ],
    },
    "Complications": {
        "keywords": [
            "complication", "reoperation", "revision",
            "surgical site infection", "dural tear",
            "CSF leak", "pseudarthrosis", "nonunion",
            "hardware failure", "screw loosening",
            "adjacent segment disease",
            "neurological deficit", "C5 palsy",
            "dysphagia", "wound dehiscence",
        ],
    },
    "Outcomes": {
        "keywords": [
            "outcome", "patient-reported", "PRO", "PROM",
            "ODI", "NDI", "VAS", "SF-36", "EQ-5D",
            "JOA score", "Nurick", "mJOA",
            "return to work", "quality of life",
            "satisfaction", "follow-up",
            "cost-effectiveness", "cost analysis",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics", "biomechanical",
            "finite element", "FEA",
            "range of motion", "ROM",
            "load sharing", "stress distribution",
            "cadaveric", "cadaver",
            "stiffness", "flexibility",
            "pullout strength", "fatigue",
        ],
    },
}


@dataclass
class ScoredSpinePaper:
    paper: Paper
    is_starred: bool = False
    interest_areas: list[str] = field(default_factory=list)
    interest_scores: dict[str, float] = field(default_factory=dict)
    general_topics: list[str] = field(default_factory=list)

    @property
    def primary_interest(self) -> str:
        if not self.interest_scores:
            return ""
        return max(self.interest_scores, key=self.interest_scores.get)


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:

    TITLE_MULTIPLIER = 2.0
    INTEREST_THRESHOLD = 0.15
    TOPIC_THRESHOLD = 2

    def score_paper(self, paper: Paper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = _build_searchable_text(paper)

        for area_name, profile in INTEREST_PROFILES.items():
            score = self._score_interest(paper, full_text, profile)
            result.interest_scores[area_name] = score
            if score >= self.INTEREST_THRESHOLD:
                result.interest_areas.append(area_name)

        result.is_starred = len(result.interest_areas) > 0

        for topic_name, profile in TOPIC_PROFILES.items():
            hits = sum(
                1 for kw in profile["keywords"]
                if _text_contains(full_text, kw)
            )
            if hits >= self.TOPIC_THRESHOLD:
                result.general_topics.append(topic_name)

        return result

    def _score_interest(self, paper: Paper, full_text: str, profile: dict) -> float:
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

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredSpinePaper]:
        scored = [self.score_paper(p) for p in papers]
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]
        starred.sort(
            key=lambda x: max(x.interest_scores.values()) if x.interest_scores else 0,
            reverse=True,
        )
        result = starred + unstarred
        logger.info(
            f"Scored {len(scored)} papers: {len(starred)} starred, "
            f"{len(unstarred)} general"
        )
        return result
