"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Also evaluates method and concept relevance to the lab's four core
research pillars:
  1. NKTの恒常性維持機能
  2. NKTワクチン
  3. 整形外科
  4. 骨代謝研究
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Topic scoring profiles ─────────────────────────────────────────────

TOPIC_PROFILES: dict[str, dict] = {
    "iNKT development": {
        "primary": [
            "NKT cell homeostasis", "iNKT homeostasis",
            "NKT cell development", "iNKT development",
            "NKT cell maintenance", "NKT survival",
            "NKT cell maturation", "NKT cell selection",
            "NKT cell emigration", "tissue-resident NKT",
            "tissue resident NKT", "peripheral NKT",
            "NKT cell differentiation",
        ],
        "secondary": [
            "PLZF", "NKT1", "NKT2", "NKT17",
            "stage 0", "stage 1", "stage 2", "stage 3",
            "Vα14", "Valpha14", "Vα24", "Valpha24",
            "CD1d", "α-GalCer", "alpha-GalCer",
            "NKT cell subset", "NKT cell proliferation",
            "NKT cell turnover", "IL-7 NKT", "IL-15 NKT",
            "invariant NKT", "iNKT cell",
            "NKT cell apoptosis",
        ],
        "context": [
            "lipid antigen", "glycolipid",
            "NKT cell regulation", "NKT tolerance",
            "steady state", "homeostasis",
        ],
    },
    "Thymus / development": {
        "primary": [
            "thymic NKT", "thymus NKT", "thymocyte NKT",
            "thymic selection NKT", "NKT thymic development",
            "NKT positive selection", "NKT negative selection",
        ],
        "secondary": [
            "thymus", "thymic", "thymocyte",
            "double positive", "DP thymocyte",
            "cortical thymic", "medullary thymic",
            "T cell development", "T cell selection",
        ],
        "context": [
            "development", "selection", "maturation",
        ],
    },
    "NKT-B cell": {
        "primary": [
            "NKT B cell", "NKT-B cell",
            "CXCR6 NKT", "CXCL16 NKT",
            "NKT follicular", "NKT germinal center",
            "NKT antibody", "NKT immunoglobulin",
        ],
        "secondary": [
            "B cell NKT", "NKT help B",
            "NKT marginal zone", "NKT B cell interaction",
        ],
        "context": [
            "B cell", "germinal center", "antibody response",
        ],
    },
    "B cell tolerance": {
        "primary": [
            "B cell tolerance", "NKT B cell tolerance",
            "NKT autoreactive B", "NKT B cell regulation",
            "NKT B cell suppression",
        ],
        "secondary": [
            "autoreactive B", "B cell anergy",
            "B cell deletion", "B cell regulation",
            "self-reactive B cell",
        ],
        "context": [
            "tolerance", "self-reactive", "autoreactive",
        ],
    },
    "Osteoimmunology": {
        "primary": [
            "osteoimmunology", "NKT bone",
            "NKT osteoclast", "NKT osteoblast",
            "NKT bone marrow", "NKT joint",
            "immune bone interaction",
        ],
        "secondary": [
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "OPG", "osteoprotegerin",
            "bone remodeling", "bone resorption", "bone formation",
            "bone metabolism", "bone mineral density",
            "osteoporosis", "bone healing",
            "fracture", "orthopedic", "orthopaedic",
            "arthroplasty", "osteoarthritis",
            "rheumatoid arthritis", "synovial",
            "musculoskeletal",
        ],
        "context": [
            "bone", "skeletal", "calcium metabolism",
            "vitamin D bone", "PTH", "parathyroid",
            "Wnt signaling bone", "BMP",
            "cartilage", "joint",
        ],
    },
    "Autoimmunity / SLE": {
        "primary": [
            "NKT autoimmune", "NKT lupus", "NKT SLE",
            "NKT autoimmunity", "NKT regulatory",
        ],
        "secondary": [
            "autoimmune", "lupus", "SLE",
            "systemic lupus", "autoimmunity",
            "immune tolerance", "self-reactive",
            "NKT suppression", "NKT regulation",
        ],
        "context": [
            "tolerance", "regulatory", "suppression",
        ],
    },
    "Metabolism": {
        "primary": [
            "NKT metabolism", "NKT lipid metabolism",
            "NKT adipose", "NKT liver metabolism",
            "NKT metabolic", "iNKT metabolism",
        ],
        "secondary": [
            "lipid metabolism NKT", "metabolic syndrome",
            "obesity NKT", "adipose tissue",
            "fatty liver", "NASH", "NAFLD",
            "NKT glycolysis", "NKT oxidative phosphorylation",
            "metabolic reprogramming",
        ],
        "context": [
            "metabolism", "metabolic", "lipid", "glucose",
        ],
    },
    "Tumor immunity": {
        "primary": [
            "NKT vaccine", "NKT cell therapy",
            "NKT immunotherapy", "NKT anti-tumor",
            "NKT cancer", "CAR-NKT",
            "chimeric antigen receptor NKT",
            "NKT adoptive transfer",
            "α-GalCer vaccine", "NKT adjuvant",
        ],
        "secondary": [
            "NKT cell activation", "NKT cytokine",
            "dendritic cell NKT", "NKT cell clinical",
            "NKT cell trial", "NKT cell expansion",
            "NKT immunosurveillance",
            "tumor microenvironment NKT",
            "anti-tumor", "antitumor",
            "cancer immunotherapy", "tumor rejection",
        ],
        "context": [
            "tumor", "cancer", "malignancy",
            "checkpoint", "PD-1", "PD-L1",
            "immunotherapy", "cell therapy",
        ],
    },
    "Infection": {
        "primary": [
            "NKT infection", "NKT pathogen",
            "NKT antimicrobial", "NKT viral",
            "NKT bacterial",
        ],
        "secondary": [
            "infection NKT", "pathogen NKT",
            "influenza NKT", "tuberculosis NKT",
            "malaria NKT", "HIV NKT", "hepatitis NKT",
            "sepsis NKT",
        ],
        "context": [
            "infection", "pathogen", "virus", "bacteria",
            "antimicrobial",
        ],
    },
    "Cytokines (IL-4/IFNγ)": {
        "primary": [
            "NKT IL-4", "NKT IFN-γ", "NKT IFNγ",
            "NKT interferon gamma", "NKT interleukin-4",
            "NKT cytokine production",
        ],
        "secondary": [
            "IL-4", "IFN-γ", "IFNγ", "interferon gamma",
            "IL-12 NKT", "IL-17 NKT", "IL-21 NKT",
            "NKT cytokine", "Th1 Th2 NKT",
            "cytokine bias",
        ],
        "context": [
            "cytokine", "interleukin", "interferon",
        ],
    },
    "TCR repertoire": {
        "primary": [
            "NKT TCR", "iNKT TCR", "NKT T cell receptor",
            "NKT TCR repertoire", "semi-invariant TCR",
        ],
        "secondary": [
            "TCR repertoire", "TCR diversity",
            "Vβ chain", "Vbeta", "CDR3",
            "TCR signaling NKT", "TCR affinity",
        ],
        "context": [
            "TCR", "T cell receptor", "repertoire",
        ],
    },
    "Methods / Omics": {
        "primary": [
            "NKT cell protocol", "NKT methodology",
        ],
        "secondary": [
            "CyTOF", "mass cytometry",
            "spectral flow cytometry",
            "protocol", "methodology",
        ],
        "context": [
            "high-throughput", "method",
        ],
    },
    "scRNA-seq / spatial": {
        "primary": [
            "single-cell NKT", "scRNA-seq NKT",
            "CITE-seq NKT", "spatial transcriptomics NKT",
        ],
        "secondary": [
            "scRNA-seq", "single-cell RNA",
            "ATAC-seq", "ChIP-seq", "CITE-seq",
            "spatial transcriptomics", "multiome",
            "single cell analysis",
        ],
        "context": [
            "RNA-seq", "sequencing", "bioinformatics",
            "computational",
        ],
    },
}


# ── Method profiles ──────────────────────────────────────────────────────
# Methods/techniques that could be applied to the lab's research

METHOD_PROFILES: dict[str, dict] = {
    "flow_cytometry": {
        "keywords": [
            "flow cytometry", "FACS", "fluorescence-activated",
            "spectral flow", "CyTOF", "mass cytometry",
            "intracellular staining", "surface marker",
            "cell sorting", "multicolor",
        ],
        "label": "フローサイトメトリー",
    },
    "single_cell_omics": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "single cell RNA",
            "CITE-seq", "ATAC-seq", "multiome",
            "spatial transcriptomics", "Visium",
            "10x Genomics", "single-cell analysis",
            "single cell sequencing", "scATAC",
        ],
        "label": "シングルセル解析",
    },
    "in_vivo_mouse": {
        "keywords": [
            "knockout mice", "KO mice", "transgenic mice",
            "conditional knockout", "Cre-lox", "CreERT2",
            "bone marrow chimera", "adoptive transfer",
            "in vivo imaging", "bioluminescence",
            "lineage tracing", "fate mapping",
            "parabiosis", "competitive reconstitution",
        ],
        "label": "マウスin vivoモデル",
    },
    "cell_culture_expansion": {
        "keywords": [
            "cell expansion", "ex vivo expansion",
            "in vitro culture", "cell culture",
            "stimulation protocol", "co-culture",
            "feeder cell", "cytokine cocktail",
            "GMP", "good manufacturing practice",
            "cell manufacturing",
        ],
        "label": "細胞培養・増殖",
    },
    "bone_analysis": {
        "keywords": [
            "micro-CT", "microCT", "μCT",
            "bone histomorphometry", "TRAP staining",
            "ALP staining", "alizarin red",
            "calcein labeling", "bone mineral density",
            "BMD", "DXA", "DEXA",
            "mechanical testing", "three-point bending",
            "osteoclast assay", "RANKL assay",
        ],
        "label": "骨解析",
    },
    "clinical_trial": {
        "keywords": [
            "clinical trial", "phase I", "phase II", "phase III",
            "randomized controlled", "RCT",
            "patient cohort", "clinical study",
            "dose escalation", "safety profile",
            "adverse event", "PBMC",
            "GMP manufacturing",
        ],
        "label": "臨床試験",
    },
    "immunoassay": {
        "keywords": [
            "ELISA", "ELISPOT", "Luminex",
            "cytokine assay", "multiplex",
            "intracellular cytokine", "ICS",
            "cytotoxicity assay", "51Cr release",
            "chromium release", "killing assay",
            "CD107a degranulation",
        ],
        "label": "免疫アッセイ",
    },
    "imaging": {
        "keywords": [
            "confocal microscopy", "two-photon",
            "intravital imaging", "immunofluorescence",
            "immunohistochemistry", "IHC",
            "multiplex imaging", "tissue clearing",
            "light sheet", "PET imaging",
        ],
        "label": "イメージング",
    },
    "gene_editing": {
        "keywords": [
            "CRISPR", "Cas9", "guide RNA", "gRNA",
            "gene editing", "gene knockout",
            "lentiviral", "retroviral transduction",
            "CAR construct", "chimeric antigen receptor",
        ],
        "label": "遺伝子編集",
    },
}

# ── Research pillar definitions ──────────────────────────────────────────
# Maps each core research area to concept keywords for recommendation

RESEARCH_PILLARS: dict[str, dict] = {
    "NKT恒常性維持": {
        "concept_keywords": [
            "homeostasis", "homeostatic", "maintenance",
            "survival", "proliferation", "turnover",
            "tissue-resident", "tissue resident",
            "peripheral maintenance", "steady state",
            "cell death", "apoptosis",
            "IL-7", "IL-15", "tonic signaling",
            "self-renewal", "quiescence",
            "emigration", "retention",
        ],
        "description": "NKT細胞が定常状態でどのように維持されるか",
    },
    "NKTワクチン": {
        "concept_keywords": [
            "vaccine", "vaccination", "adjuvant",
            "dendritic cell", "antigen presentation",
            "α-GalCer", "alpha-GalCer", "glycolipid antigen",
            "cell therapy", "immunotherapy",
            "adoptive transfer", "CAR-NKT",
            "anti-tumor", "antitumor",
            "tumor rejection", "cancer vaccine",
            "clinical trial", "GMP",
            "cell expansion", "ex vivo",
        ],
        "description": "NKT細胞を利用したがんワクチン・細胞治療",
    },
    "整形外科": {
        "concept_keywords": [
            "orthopedic", "orthopaedic",
            "fracture", "fracture healing",
            "arthroplasty", "joint replacement",
            "osteoarthritis", "rheumatoid arthritis",
            "spine", "spinal", "vertebral",
            "implant", "prosthesis",
            "surgical", "perioperative",
            "rehabilitation", "musculoskeletal",
            "cartilage", "meniscus", "ligament",
            "tendon", "rotator cuff",
        ],
        "description": "整形外科手術・疾患とNKT細胞の関与",
    },
    "骨代謝": {
        "concept_keywords": [
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "OPG", "osteoprotegerin",
            "M-CSF", "RANK",
            "bone resorption", "bone formation",
            "osteoporosis", "bone loss",
            "bone mineral density", "BMD",
            "calcium", "phosphate",
            "vitamin D", "PTH", "parathyroid",
            "Wnt", "BMP", "sclerostin",
            "glucocorticoid-induced osteoporosis",
            "bone marrow", "bone marrow niche",
        ],
        "description": "骨代謝メカニズムとNKT細胞の役割",
    },
}


# ── Scored article result ───────────────────────────────────────────────

@dataclass
class ScoredArticle:
    """Scoring result for a paper."""
    paper: Paper
    total_score: float = 0.0
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    matched_methods: list[str] = field(default_factory=list)
    matched_pillars: list[str] = field(default_factory=list)
    method_score: float = 0.0
    pillar_score: float = 0.0
    recommendation_reason: str = ""

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return "iNKT development"
        return max(self.topic_scores, key=self.topic_scores.get)


# ── Scorer ──────────────────────────────────────────────────────────────

def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class RelevanceScorer:

    TITLE_MULTIPLIER = 2.0
    SCORE_THRESHOLD = 0.15  # minimum to assign a topic
    METHOD_BONUS = 0.10
    PILLAR_BONUS = 0.15

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        base_score = max(result.topic_scores.values()) if result.topic_scores else 0.0

        result.matched_methods = self._detect_methods(full_text)
        result.method_score = min(len(result.matched_methods) * self.METHOD_BONUS, 0.3)

        result.matched_pillars = self._detect_pillars(full_text)
        result.pillar_score = min(len(result.matched_pillars) * self.PILLAR_BONUS, 0.3)

        result.total_score = min(base_score + result.method_score + result.pillar_score, 1.0)
        result.recommendation_reason = self._generate_reason(result)
        return result

    def _score_topic(self, paper: Paper, full_text: str, profile: dict) -> float:
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

    def _detect_methods(self, full_text: str) -> list[str]:
        matched = []
        for method_id, profile in METHOD_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    matched.append(profile["label"])
                    break
        return matched

    def _detect_pillars(self, full_text: str) -> list[str]:
        matched = []
        for pillar_name, profile in RESEARCH_PILLARS.items():
            hit_count = sum(
                1 for kw in profile["concept_keywords"]
                if _text_contains(full_text, kw)
            )
            if hit_count >= 2:
                matched.append(pillar_name)
        return matched

    def _generate_reason(self, result: ScoredArticle) -> str:
        parts = []

        if result.matched_pillars:
            pillar_str = "・".join(result.matched_pillars)
            parts.append(f"研究テーマとの関連: {pillar_str}")

        if result.matched_methods:
            method_str = "、".join(result.matched_methods)
            parts.append(f"活用可能な手法: {method_str}")

        if result.matched_topics:
            parts.append(f"トピック: {', '.join(result.matched_topics)}")

        if parts:
            return " | ".join(parts)
        return "NKT細胞関連（一般）"

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
