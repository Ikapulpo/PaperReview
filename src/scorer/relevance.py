"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Two-axis scoring:
  - CONCEPT axis: Does the paper address a research question we care about?
  - METHOD axis: Does the paper use or develop methods applicable to our work?
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Lab research focus (for recommendation text) ──────────────────────

LAB_RESEARCH_AREAS = {
    "NKT恒常性維持": {
        "description": "NKT細胞の恒常性維持メカニズム（組織常在NKT、IL-7/IL-15シグナル、生存・増殖・アポトーシス制御）",
        "keywords": ["homeostasis", "maintenance", "survival", "turnover",
                     "tissue-resident", "IL-7", "IL-15", "PLZF", "steady state"],
    },
    "NKTワクチン": {
        "description": "NKT細胞を利用したワクチン・免疫療法（α-GalCer、CAR-NKT、腫瘍免疫）",
        "keywords": ["vaccine", "immunotherapy", "α-GalCer", "alpha-GalCer",
                     "CAR-NKT", "cell therapy", "adjuvant", "dendritic cell",
                     "anti-tumor", "clinical trial"],
    },
    "整形外科・骨代謝": {
        "description": "骨免疫学・骨代謝研究（RANKL/OPG、骨リモデリング、骨粗鬆症、関節炎）",
        "keywords": ["bone", "osteoclast", "osteoblast", "RANKL", "OPG",
                     "osteoporosis", "fracture", "arthritis", "joint",
                     "cartilage", "orthopedic", "skeletal", "bone marrow"],
    },
}


# ── Method profiles for method-axis scoring ───────────────────────────

METHOD_PROFILES: dict[str, dict] = {
    "フローサイトメトリー・CyTOF": {
        "terms": ["flow cytometry", "CyTOF", "mass cytometry",
                  "spectral flow", "FACS", "cell sorting",
                  "intracellular staining", "surface marker",
                  "tetramer", "CD1d tetramer", "multicolor"],
        "applicability": "NKT細胞のサブセット解析や活性化マーカー解析に転用可能",
    },
    "scRNA-seq・空間オミクス": {
        "terms": ["scRNA-seq", "single-cell RNA", "CITE-seq", "spatial transcriptomics",
                  "multiome", "ATAC-seq", "single cell", "10x Genomics",
                  "Visium", "MERFISH", "single-cell analysis"],
        "applicability": "NKT細胞の不均一性解析や組織内局在解析に応用可能",
    },
    "in vivoモデル": {
        "terms": ["knockout", "conditional knockout", "Cre-lox",
                  "bone marrow chimera", "adoptive transfer", "transgenic",
                  "lineage tracing", "fate mapping", "parabiosis",
                  "disease model", "murine model", "mouse model",
                  "in vivo", "tumor model"],
        "applicability": "NKT細胞の機能解析やin vivo恒常性研究のモデル系として参考になる",
    },
    "骨代謝実験系": {
        "terms": ["micro-CT", "μCT", "bone histomorphometry",
                  "osteoclast differentiation", "TRAP staining",
                  "bone mineral density", "DXA", "mechanical testing",
                  "osteoclastogenesis", "bone resorption assay",
                  "bone formation", "bone remodeling"],
        "applicability": "骨代謝研究のアッセイ系として直接活用可能",
    },
    "細胞培養・機能アッセイ": {
        "terms": ["co-culture", "cytotoxicity assay", "ELISA", "ELISpot",
                  "proliferation assay", "suppression assay",
                  "killing assay", "cytokine measurement",
                  "in vitro expansion", "cell activation",
                  "cytotoxicity", "IFN-γ", "IFNγ",
                  "ex vivo", "cell expansion"],
        "applicability": "NKT細胞の機能評価系として活用可能",
    },
    "臨床研究デザイン": {
        "terms": ["clinical trial", "phase I", "phase II", "patient cohort",
                  "randomized", "prospective", "retrospective",
                  "biomarker", "overall survival", "progression-free",
                  "clinical translation", "off-the-shelf",
                  "GMP", "clinical progress", "patients"],
        "applicability": "NKTワクチン臨床試験のデザインや評価指標の参考になる",
    },
    "バイオインフォマティクス": {
        "terms": ["gene signature", "pathway analysis", "GSEA",
                  "network analysis", "machine learning", "clustering",
                  "trajectory analysis", "pseudotime", "DEG",
                  "transcriptome", "proteomics", "proteomic",
                  "mass spectrometry"],
        "applicability": "NKT細胞のオミクスデータ解析手法として応用可能",
    },
    "イメージング": {
        "terms": ["confocal", "two-photon", "intravital imaging",
                  "immunofluorescence", "immunohistochemistry", "IHC",
                  "live imaging", "multiplex imaging", "TUNEL",
                  "histology", "histological"],
        "applicability": "NKT細胞の組織内動態や骨髄内分布の可視化に応用可能",
    },
    "腫瘍微小環境解析": {
        "terms": ["tumor microenvironment", "TME", "immune landscape",
                  "immune infiltration", "tumor-infiltrating",
                  "immunosuppressive microenvironment",
                  "immune checkpoint", "PD-1", "PD-L1"],
        "applicability": "NKT細胞の腫瘍内浸潤・機能に関する知見として活用可能",
    },
}


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


# ── Scored article result ───────────────────────────────────────────────

@dataclass
class ScoredArticle:
    """Scoring result for a paper."""
    paper: Paper
    total_score: float = 0.0
    concept_score: float = 0.0
    method_score: float = 0.0
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    matched_methods: list[str] = field(default_factory=list)
    concept_reasons: list[str] = field(default_factory=list)
    method_reasons: list[str] = field(default_factory=list)
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
    METHOD_THRESHOLD = 0.10  # minimum to assign a method
    CONCEPT_WEIGHT = 0.6
    METHOD_WEIGHT = 0.4

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        # Concept-axis scoring (topic matching)
        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        result.concept_score = max(result.topic_scores.values()) if result.topic_scores else 0.0

        # Method-axis scoring
        result.method_score, result.matched_methods = self._score_methods(full_text)

        # Combined score (weighted)
        result.total_score = min(
            self.CONCEPT_WEIGHT * result.concept_score
            + self.METHOD_WEIGHT * result.method_score,
            1.0,
        )

        # Generate detailed recommendation reasons
        result.concept_reasons = self._generate_concept_reasons(result)
        result.method_reasons = self._generate_method_reasons(result, full_text)
        result.recommendation_reason = self._generate_full_recommendation(result)
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

    def _score_methods(self, full_text: str) -> tuple[float, list[str]]:
        """Score paper by experimental methods applicable to our research."""
        matched = []
        total_score = 0.0

        for method_name, profile in METHOD_PROFILES.items():
            hits = sum(1 for t in profile["terms"] if _text_contains(full_text, t))
            if hits >= 2:
                matched.append(method_name)
                total_score += 0.25
            elif hits == 1:
                total_score += 0.08

        return min(total_score, 1.0), matched

    def _generate_concept_reasons(self, result: ScoredArticle) -> list[str]:
        """Generate concept-axis recommendation reasons."""
        reasons = []
        full_text = _build_searchable_text(result.paper)

        for area_name, area in LAB_RESEARCH_AREAS.items():
            hits = [kw for kw in area["keywords"] if _text_contains(full_text, kw)]
            if hits:
                reasons.append(
                    f"【{area_name}】{area['description']}に関連 "
                    f"(キーワード: {', '.join(hits[:3])})"
                )

        if not reasons and result.matched_topics:
            reasons.append(
                f"NKT研究分野（{', '.join(result.matched_topics[:3])}）に分類される論文"
            )

        return reasons

    def _generate_method_reasons(self, result: ScoredArticle, full_text: str) -> list[str]:
        """Generate method-axis recommendation reasons."""
        reasons = []

        for method_name in result.matched_methods:
            profile = METHOD_PROFILES[method_name]
            reasons.append(
                f"【{method_name}】{profile['applicability']}"
            )

        return reasons

    def _generate_full_recommendation(self, result: ScoredArticle) -> str:
        """Generate a combined recommendation text."""
        parts = []

        if result.concept_reasons:
            parts.append("＜コンセプト面＞")
            for r in result.concept_reasons[:2]:
                parts.append(f"  {r}")

        if result.method_reasons:
            parts.append("＜メソッド面＞")
            for r in result.method_reasons[:2]:
                parts.append(f"  {r}")

        if not parts:
            return "NKT細胞に関する一般的な論文"

        return "\n".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
