"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Also annotates papers with:
  - Matched methods and their potential applications to the lab
  - Matched concepts and their relevance to the lab's research themes
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

METHOD_PROFILES: dict[str, dict] = {
    "フローサイトメトリー": {
        "keywords": [
            "flow cytometry", "FACS", "spectral flow cytometry",
            "cell sorting", "intracellular staining",
        ],
        "application": "NKTサブセット解析やPLZF発現パターンの解析に応用可能",
    },
    "scRNA-seq / single-cell": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "single cell RNA",
            "10x Genomics", "CITE-seq", "single-cell analysis",
        ],
        "application": "NKT細胞の不均一性・サブセット特性の網羅的解析に応用可能",
    },
    "CyTOF / mass cytometry": {
        "keywords": ["CyTOF", "mass cytometry"],
        "application": "NKTサブセットの多パラメータ同時解析に応用可能",
    },
    "空間トランスクリプトミクス": {
        "keywords": [
            "spatial transcriptomics", "spatial RNA",
            "MERFISH", "Visium", "spatial omics",
        ],
        "application": "組織内NKT細胞の局在と周辺環境の解析に応用可能",
    },
    "マウスモデル": {
        "keywords": [
            "mouse model", "murine model", "knockout mice",
            "transgenic mice", "in vivo model",
        ],
        "application": "NKT関連マウスモデルの実験デザインに参考",
    },
    "臨床研究": {
        "keywords": [
            "clinical trial", "clinical study", "patient cohort",
            "cohort study", "clinical sample",
        ],
        "application": "患者検体を用いたバイオマーカー研究に応用可能",
    },
    "食事介入": {
        "keywords": [
            "dietary intervention", "dietary supplementation",
            "diet-induced", "nutritional",
            "oral administration",
        ],
        "application": "NKTワクチンの経口投与や代謝介入研究に応用可能",
    },
    "細胞治療 / 養子移入": {
        "keywords": [
            "cell therapy", "adoptive transfer", "CAR-NKT",
            "CAR-T", "cell expansion", "ex vivo expansion",
        ],
        "application": "NKTワクチン・NKT細胞治療の開発に直結",
    },
    "骨イメージング": {
        "keywords": [
            "micro-CT", "microCT", "bone imaging",
            "bone histomorphometry", "DEXA", "DXA",
            "bone mineral density",
        ],
        "application": "骨代謝・整形外科研究の表現型解析に直接応用可能",
    },
    "破骨細胞分化アッセイ": {
        "keywords": [
            "osteoclast differentiation", "osteoclastogenesis",
            "TRAP staining", "RANKL stimulation",
            "bone resorption assay",
        ],
        "application": "骨免疫学・骨代謝研究の機能解析に直接応用可能",
    },
    "ナノ粒子ドラッグデリバリー": {
        "keywords": [
            "nanoparticle", "lipid nanoparticle", "LNP",
            "drug delivery system", "targeted delivery",
        ],
        "application": "NKTリガンドの標的送達やワクチンアジュバント開発に応用可能",
    },
    "マイクロバイオーム解析": {
        "keywords": [
            "microbiome", "microbiota", "16S rRNA",
            "metagenomics", "germ-free", "gnotobiotic",
        ],
        "application": "腸内環境によるNKT活性化・恒常性制御の研究に応用可能",
    },
    "ケモカイン / サイトカインアッセイ": {
        "keywords": [
            "chemokine assay", "cytokine assay", "ELISA",
            "multiplex cytokine", "Luminex",
            "intracellular cytokine staining",
        ],
        "application": "NKT細胞の機能評価・活性化マーカー解析に応用可能",
    },
    "胸腺移出 / 発生解析": {
        "keywords": [
            "thymic egress", "thymic emigration", "thymic output",
            "thymic transplant", "intrathymic injection",
            "RAG2-GFP", "recent thymic emigrant",
        ],
        "application": "iNKT細胞の末梢供給・恒常性維持メカニズムの解析に直接応用可能",
    },
    "multi-omics": {
        "keywords": [
            "multi-omics", "multiomics", "integrated omics",
            "proteomics", "metabolomics", "epigenomics",
        ],
        "application": "NKTの網羅的分子プロファイリングに応用可能",
    },
    "ssGSEA / 免疫細胞推定": {
        "keywords": [
            "ssGSEA", "CIBERSORT", "immune deconvolution",
            "immune cell estimation", "xCell",
        ],
        "application": "公開データからNKT関連シグネチャのマイニングに応用可能",
    },
}


# ── Concept profiles ─────────────────────────────────────────────────────

CONCEPT_PROFILES: dict[str, dict] = {
    "NKT恒常性維持": {
        "keywords": [
            "NKT homeostasis", "iNKT homeostasis",
            "NKT maintenance", "NKT cell survival",
            "tissue-resident NKT", "NKT turnover",
        ],
        "relevance": "研究室の中心テーマ — NKT恒常性維持機能の理解に直結",
    },
    "胸腺発生 / 分化": {
        "keywords": [
            "thymic development NKT", "T cell development",
            "thymic selection", "thymic output",
            "innate-like T cell development",
        ],
        "relevance": "iNKT発生・分化プログラムの理解に重要",
    },
    "NKT-DC相互作用": {
        "keywords": [
            "NKT dendritic", "NKT cDC1", "NKT DC interaction",
            "NKT antigen presentation", "XCL1",
            "NKT cross-presentation",
        ],
        "relevance": "NKTワクチンの作用機序 — DC活性化を介した免疫誘導に直結",
    },
    "抗腫瘍免疫": {
        "keywords": [
            "anti-tumor immunity", "antitumor immunity",
            "tumor rejection", "immunosurveillance",
            "cancer immunotherapy NKT",
        ],
        "relevance": "NKTワクチン開発 — 臨床応用の基盤研究",
    },
    "免疫チェックポイント併用": {
        "keywords": [
            "checkpoint inhibitor", "PD-1 NKT", "PD-L1",
            "anti-PD", "immune checkpoint",
            "checkpoint combination",
        ],
        "relevance": "NKTワクチン + ICI併用療法の可能性",
    },
    "骨免疫学": {
        "keywords": [
            "osteoimmunology", "bone immune interaction",
            "osteoclast immune", "osteoblast immune",
            "bone remodeling immune", "RANKL immune",
        ],
        "relevance": "骨代謝・整形外科研究とNKTの接点",
    },
    "骨髄微小環境": {
        "keywords": [
            "bone marrow niche", "bone marrow microenvironment",
            "hematopoietic niche", "bone marrow stroma",
        ],
        "relevance": "骨髄環境でのNKT機能・骨代謝への影響",
    },
    "腸管免疫 / 腸内細菌-免疫軸": {
        "keywords": [
            "gut immune", "intestinal immune",
            "microbiome immunity", "gut-immune axis",
            "mucosal immunity", "intestinal NKT",
        ],
        "relevance": "腸内環境によるNKT活性化・恒常性制御",
    },
    "組織常在免疫": {
        "keywords": [
            "tissue-resident immunity", "tissue resident",
            "tissue homing", "tissue seeding",
            "organ-specific immunity",
        ],
        "relevance": "組織特異的NKT細胞の機能と恒常性",
    },
    "免疫寛容 / 自己寛容": {
        "keywords": [
            "immune tolerance", "self-tolerance",
            "peripheral tolerance", "central tolerance",
            "tolerogenic",
        ],
        "relevance": "NKT細胞を介した免疫寛容誘導メカニズム",
    },
    "代謝リプログラミング": {
        "keywords": [
            "metabolic reprogramming", "immunometabolism",
            "glycolysis immune", "fatty acid metabolism immune",
            "lipid metabolism immune",
        ],
        "relevance": "NKT細胞の代謝制御と機能の関係",
    },
}


# ── Scored article result ───────────────────────────────────────────────

@dataclass
class MethodMatch:
    """A matched method and its application to the lab."""
    name: str
    application: str


@dataclass
class ConceptMatch:
    """A matched concept and its relevance to the lab."""
    name: str
    relevance: str


@dataclass
class ScoredArticle:
    """Scoring result for a paper."""
    paper: Paper
    total_score: float = 0.0
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    matched_methods: list[MethodMatch] = field(default_factory=list)
    matched_concepts: list[ConceptMatch] = field(default_factory=list)
    recommendation_reason: str = ""

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return "iNKT development"
        return max(self.topic_scores, key=self.topic_scores.get)

    @property
    def research_theme(self) -> str:
        """Map primary topic to lab research theme (Japanese)."""
        theme_map = {
            "iNKT development": "NKT恒常性維持",
            "Thymus / development": "NKT恒常性維持",
            "NKT-B cell": "NKT恒常性維持",
            "B cell tolerance": "NKT恒常性維持",
            "Tumor immunity": "NKTワクチン",
            "Osteoimmunology": "整形外科・骨代謝",
        }
        return theme_map.get(self.primary_topic, "")


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

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        result.total_score = max(result.topic_scores.values()) if result.topic_scores else 0.0
        result.matched_methods = self._match_methods(full_text)
        result.matched_concepts = self._match_concepts(full_text)
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

    def _match_methods(self, full_text: str) -> list[MethodMatch]:
        matches = []
        for name, profile in METHOD_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    matches.append(MethodMatch(
                        name=name,
                        application=profile["application"],
                    ))
                    break
        return matches

    def _match_concepts(self, full_text: str) -> list[ConceptMatch]:
        matches = []
        for name, profile in CONCEPT_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    matches.append(ConceptMatch(
                        name=name,
                        relevance=profile["relevance"],
                    ))
                    break
        return matches

    def _generate_reason(self, result: ScoredArticle) -> str:
        parts = []

        if result.research_theme:
            parts.append(f"研究テーマ関連: {result.research_theme}")

        if result.matched_methods:
            method_strs = [
                f"{m.name} → {m.application}"
                for m in result.matched_methods[:3]
            ]
            parts.append("手法: " + " / ".join(method_strs))

        if result.matched_concepts:
            concept_strs = [
                f"{c.name} — {c.relevance}"
                for c in result.matched_concepts[:3]
            ]
            parts.append("コンセプト: " + " / ".join(concept_strs))

        if not parts:
            if result.matched_topics:
                return f"Topics: {', '.join(result.matched_topics)}"
            return "NKT cell related"

        return "\n".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
