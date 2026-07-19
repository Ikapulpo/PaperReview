"""Relevance scoring for spine papers against user interest areas.

Interest areas (marked with star):
  1. Spine surgery and AI
  2. Surgical indication assessment
  3. Basic spine research (disc, neural tissue, osteoimmunology, bone metabolism)
  4. Biomaterials (basic or clinical evaluation)

General topics for classification:
  Degenerative, Deformity, Trauma, Tumor, Infection, OVF/Osteoporosis,
  Cervical, Lumbar, Minimally invasive, Endoscopic, Navigation/Robotics,
  Complications, Outcomes, Biomechanics
"""

import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

INTEREST_PROFILES: dict[str, dict] = {
    "脊椎外科とAI": {
        "primary": [
            "machine learning", "deep learning", "artificial intelligence",
            "neural network", "convolutional neural network", "CNN",
            "random forest", "gradient boosting", "XGBoost",
            "natural language processing", "NLP",
            "large language model", "LLM", "ChatGPT", "GPT-4",
            "computer vision", "image segmentation",
            "automated detection", "automated classification",
            "predictive model", "prediction model",
        ],
        "secondary": [
            "radiomics", "deep neural", "transfer learning",
            "ResNet", "U-Net", "transformer",
            "AUC", "AUROC", "ROC curve",
            "ensemble model", "support vector machine", "SVM",
            "logistic regression model", "risk calculator",
            "web-based tool", "web-based calculator",
            "decision tree", "Bayesian network",
        ],
        "context": [
            "algorithm", "classifier", "prediction",
            "model performance", "validation cohort",
        ],
    },
    "脊椎外科手術の適応評価": {
        "primary": [
            "surgical indication", "patient selection",
            "surgical decision", "treatment selection",
            "operative versus nonoperative", "operative vs conservative",
            "surgical candidacy", "shared decision",
            "outcome prediction", "prognostic factor",
            "predictive factor", "preoperative predictor",
            "risk stratification", "risk prediction",
            "MCID", "minimum clinically important difference",
            "patient-reported outcome", "satisfaction predictor",
        ],
        "secondary": [
            "treatment algorithm", "clinical decision",
            "surgical planning", "indication for surgery",
            "cost-effectiveness", "value-based",
            "benchmark", "risk calculator",
            "frailty", "frailty index",
            "patient optimization", "preoperative optimization",
            "surgical threshold", "outcome measure",
        ],
        "context": [
            "outcome", "predictor", "selection criteria",
            "appropriate use", "appropriateness",
        ],
    },
    "脊椎の基礎研究": {
        "primary": [
            "intervertebral disc degeneration", "disc degeneration",
            "nucleus pulposus", "annulus fibrosus", "endplate",
            "notochordal cell", "disc cell",
            "nerve root", "dorsal root ganglion", "DRG",
            "spinal cord injury", "neural regeneration",
            "neuropathic pain mechanism", "central sensitization",
            "osteoimmunology", "bone immunology",
            "osteoclastogenesis", "osteoblastogenesis",
            "bone metabolism", "bone remodeling",
            "RANKL", "OPG", "osteoprotegerin",
            "Wnt signaling", "BMP signaling",
            "in vitro", "in vivo", "animal model",
            "cell culture", "organ culture",
        ],
        "secondary": [
            "proteoglycan", "aggrecan", "collagen type II",
            "matrix metalloproteinase", "MMP",
            "inflammatory cytokine", "TNF-alpha", "IL-1",
            "growth factor", "TGF-beta", "IGF",
            "stem cell", "mesenchymal stem cell", "MSC",
            "gene expression", "signaling pathway",
            "mechanotransduction", "mechanical loading",
            "apoptosis", "senescence", "autophagy",
            "extracellular matrix", "ECM",
            "Mendelian randomization", "GWAS",
            "epigenetics", "microRNA", "miRNA",
        ],
        "context": [
            "mechanism", "pathogenesis", "pathophysiology",
            "molecular", "cellular", "tissue engineering",
            "experimental", "laboratory", "rat", "mouse", "rabbit",
        ],
    },
    "バイオマテリアル": {
        "primary": [
            "biomaterial", "biocompatibility",
            "titanium cage", "PEEK cage", "interbody cage",
            "porous titanium", "3D-printed implant", "3D printed",
            "bone graft substitute", "bone cement",
            "hydroxyapatite", "calcium phosphate",
            "biodegradable", "bioresorbable",
            "surface coating", "surface modification",
            "scaffold", "tissue-engineered",
            "total disc replacement", "artificial disc",
            "cervical disc arthroplasty",
            "implant design", "implant material",
        ],
        "secondary": [
            "PEEK", "polyetheretherketone",
            "ceramic", "silicon nitride",
            "pedicle screw design", "rod material",
            "cobalt-chromium", "titanium alloy",
            "osseointegration", "bone ingrowth",
            "cage subsidence", "fusion rate",
            "implant failure", "mechanical testing",
            "fatigue testing", "biomechanical testing",
            "wear debris", "corrosion",
            "drug-eluting", "antibiotic-loaded",
        ],
        "context": [
            "implant", "device", "material properties",
            "mechanical strength", "porosity",
        ],
    },
}

GENERAL_TOPIC_PROFILES: dict[str, dict] = {
    "Degenerative": {
        "keywords": [
            "degenerative", "spondylosis", "stenosis", "disc herniation",
            "spondylolisthesis", "myelopathy", "radiculopathy",
            "facet joint", "foraminal stenosis",
        ],
    },
    "Deformity": {
        "keywords": [
            "scoliosis", "kyphosis", "deformity", "spinal alignment",
            "sagittal balance", "coronal balance", "spinal curvature",
            "adult spinal deformity", "ASD", "adolescent idiopathic",
        ],
    },
    "Trauma": {
        "keywords": [
            "fracture", "trauma", "burst fracture", "dislocation",
            "spinal cord injury", "SCI", "vertebral fracture",
            "compression fracture", "chance fracture",
        ],
    },
    "Tumor": {
        "keywords": [
            "tumor", "metastasis", "metastases", "metastatic",
            "neoplasm", "cancer", "malignant", "chordoma",
            "schwannoma", "meningioma", "en bloc",
        ],
    },
    "Infection": {
        "keywords": [
            "infection", "discitis", "osteomyelitis", "abscess",
            "spondylodiscitis", "tuberculosis", "surgical site infection",
        ],
    },
    "OVF/Osteoporosis": {
        "keywords": [
            "osteoporosis", "osteoporotic", "vertebral compression fracture",
            "kyphoplasty", "vertebroplasty", "bone density",
            "bisphosphonate", "vitamin D", "DEXA",
        ],
    },
    "Cervical": {
        "keywords": [
            "cervical", "ACDF", "laminoplasty", "cervical disc",
            "anterior cervical", "posterior cervical", "odontoid",
            "atlantoaxial", "occipitocervical",
        ],
    },
    "Lumbar": {
        "keywords": [
            "lumbar", "TLIF", "PLIF", "ALIF", "XLIF", "LLIF",
            "lumbar fusion", "lumbar stenosis", "lumbar disc",
            "cauda equina",
        ],
    },
    "Minimally invasive": {
        "keywords": [
            "minimally invasive", "MIS", "tubular", "percutaneous",
            "MIS-TLIF", "lateral interbody",
        ],
    },
    "Endoscopic": {
        "keywords": [
            "endoscopic", "endoscopy", "full-endoscopic",
            "biportal endoscopic", "UBE", "uniportal",
        ],
    },
    "Navigation/Robotics": {
        "keywords": [
            "navigation", "robotic", "robot-assisted",
            "computer-assisted", "augmented reality", "3D navigation",
            "O-arm", "intraoperative CT",
        ],
    },
    "Complications": {
        "keywords": [
            "complication", "reoperation", "revision", "adverse event",
            "CSF leak", "dural tear", "wound infection",
            "pseudarthrosis", "nonunion", "hardware failure",
            "proximal junctional", "PJK", "PJF",
        ],
    },
    "Outcomes": {
        "keywords": [
            "outcome", "follow-up", "long-term", "patient satisfaction",
            "quality of life", "return to work", "functional outcome",
            "clinical outcome", "cost analysis",
        ],
    },
    "Biomechanics": {
        "keywords": [
            "biomechanics", "biomechanical", "finite element",
            "range of motion", "kinematics", "load sharing",
            "stress distribution", "cadaveric",
        ],
    },
}


@dataclass
class ScoredSpinePaper:
    paper: Paper
    is_starred: bool = False
    star_categories: list[str] = field(default_factory=list)
    general_topics: list[str] = field(default_factory=list)
    star_score: float = 0.0

    @property
    def primary_star_category(self) -> str:
        return self.star_categories[0] if self.star_categories else ""

    @property
    def all_topics(self) -> list[str]:
        return self.star_categories + self.general_topics


def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class SpineScorer:

    TITLE_MULTIPLIER = 2.0

    def score_paper(self, paper: Paper) -> ScoredSpinePaper:
        result = ScoredSpinePaper(paper=paper)
        full_text = _build_searchable_text(paper)

        for cat_name, profile in INTEREST_PROFILES.items():
            score = self._score_interest(paper, full_text, profile)
            if score >= 0.15:
                result.star_categories.append(cat_name)
                result.star_score = max(result.star_score, score)

        result.is_starred = len(result.star_categories) > 0

        for topic_name, profile in GENERAL_TOPIC_PROFILES.items():
            if any(_text_contains(full_text, kw) for kw in profile["keywords"]):
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

    def score_and_partition(
        self, papers: list[Paper],
    ) -> tuple[list[ScoredSpinePaper], list[ScoredSpinePaper]]:
        """Score papers and return (starred, unstarred) partitions."""
        scored = [self.score_paper(p) for p in papers]
        starred = sorted(
            [s for s in scored if s.is_starred],
            key=lambda x: x.star_score,
            reverse=True,
        )
        unstarred = [s for s in scored if not s.is_starred]
        return starred, unstarred
