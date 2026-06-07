"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests across three axes:
  1. Topic matching (13 categories)
  2. Method applicability (experimental techniques transferable to our research)
  3. Concept connections (conceptual frameworks relevant to our themes)

Lab research areas:
  - NKTの恒常性維持機能 (NKT homeostasis)
  - NKTワクチン (NKT vaccine / immunotherapy)
  - 整形外科 (Orthopedics)
  - 骨代謝研究 (Bone metabolism)
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Lab research areas ────────────────────────────────────────────────

LAB_RESEARCH_AREAS: dict[str, dict] = {
    "NKT恒常性維持": {
        "description_ja": "NKT細胞の恒常性維持機能の解明",
        "keywords": [
            "NKT cell homeostasis", "iNKT homeostasis",
            "NKT cell maintenance", "NKT survival",
            "NKT cell turnover", "tissue-resident NKT",
            "NKT cell development", "iNKT development",
            "NKT cell maturation", "NKT cell selection",
            "NKT cell emigration", "peripheral NKT",
            "NKT cell differentiation", "PLZF",
            "NKT1", "NKT2", "NKT17",
            "steady state NKT", "IL-7 NKT", "IL-15 NKT",
            "NKT cell regulation", "NKT tolerance",
        ],
    },
    "NKTワクチン": {
        "description_ja": "NKTワクチン・NKT細胞を利用した免疫療法の開発",
        "keywords": [
            "NKT vaccine", "NKT cell therapy",
            "NKT immunotherapy", "NKT anti-tumor",
            "CAR-NKT", "chimeric antigen receptor NKT",
            "NKT adoptive transfer", "NKT adjuvant",
            "α-GalCer vaccine", "alpha-GalCer vaccine",
            "dendritic cell NKT", "NKT cell clinical",
            "NKT cell trial", "NKT cell expansion",
            "NKT cancer", "NKT tumor",
            "NKT immunosurveillance",
        ],
    },
    "整形外科": {
        "description_ja": "整形外科領域における免疫・骨関連研究",
        "keywords": [
            "orthopedic", "orthopaedic",
            "arthroplasty", "osteoarthritis",
            "fracture", "fracture healing",
            "joint replacement", "spinal",
            "musculoskeletal", "cartilage",
            "synovial", "joint", "tendon",
            "implant", "prosthesis",
            "rheumatoid arthritis",
            "surgical", "perioperative immune",
        ],
    },
    "骨代謝研究": {
        "description_ja": "骨代謝・骨免疫学（osteoimmunology）の研究",
        "keywords": [
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "OPG", "osteoprotegerin",
            "bone resorption", "bone formation",
            "bone mineral density", "osteoporosis",
            "osteoimmunology", "bone marrow",
            "calcium metabolism", "vitamin D bone",
            "PTH", "parathyroid", "Wnt signaling bone",
            "BMP", "bone healing",
        ],
    },
}


# ── Method profiles ───────────────────────────────────────────────────

METHOD_PROFILES: dict[str, dict] = {
    "フローサイトメトリー": {
        "keywords": [
            "flow cytometry", "FACS", "CyTOF", "mass cytometry",
            "spectral flow cytometry", "intracellular staining",
            "cell sorting", "multicolor",
        ],
        "applicability": {
            "NKT恒常性維持": "NKTサブセット（NKT1/2/17）の表面マーカー解析やPLZF発現パターンの解析に応用可能",
            "NKTワクチン": "ワクチン投与後のNKT活性化・サイトカイン産生プロファイルの評価に利用可能",
            "骨代謝研究": "骨髄中のNKTや免疫細胞の表現型解析に応用可能",
        },
    },
    "シングルセル解析": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "single cell RNA",
            "CITE-seq", "ATAC-seq", "multiome",
            "spatial transcriptomics", "single cell analysis",
            "10x Genomics", "Smart-seq", "Drop-seq",
        ],
        "applicability": {
            "NKT恒常性維持": "NKTサブセットの転写プロファイルや分化軌跡の解析に有用",
            "NKTワクチン": "ワクチン応答時のNKTクローン動態や遺伝子発現変動の解析に応用可能",
            "骨代謝研究": "骨髄微小環境における免疫細胞-骨細胞クロストークの網羅的解析が可能",
        },
    },
    "in vivoモデル": {
        "keywords": [
            "knockout mouse", "knockout mice", "KO mouse", "KO mice",
            "transgenic mouse", "transgenic mice",
            "conditional knockout", "Cre-lox",
            "adoptive transfer", "bone marrow transplant",
            "chimera", "parabiosis",
            "disease model", "collagen-induced",
        ],
        "applicability": {
            "NKT恒常性維持": "遺伝子改変マウスによるNKT恒常性維持メカニズムの検証に直接応用可能",
            "NKTワクチン": "腫瘍モデルでのNKTワクチン効果検証に利用可能",
            "整形外科": "関節炎・骨折モデルでのNKT機能解析に応用可能",
            "骨代謝研究": "骨粗鬆症・骨折モデルでの免疫-骨相互作用の検証に有用",
        },
    },
    "脂質抗原・α-GalCer": {
        "keywords": [
            "α-GalCer", "alpha-GalCer", "αGalCer",
            "KRN7000", "lipid antigen", "glycolipid antigen",
            "CD1d loading", "lipid presentation",
            "lipid-pulsed dendritic cell",
        ],
        "applicability": {
            "NKT恒常性維持": "NKT活性化と恒常性維持バランスの理解に重要",
            "NKTワクチン": "α-GalCerをアジュバントとしたワクチン設計に直接関連",
        },
    },
    "骨イメージング": {
        "keywords": [
            "micro-CT", "microCT", "DEXA", "DXA",
            "bone histomorphometry", "TRAP staining",
            "calcein labeling", "alizarin red",
            "bone imaging", "μCT",
        ],
        "applicability": {
            "整形外科": "骨構造評価・治療効果判定に直接応用可能",
            "骨代謝研究": "骨量・骨微細構造の定量評価法として有用",
        },
    },
    "共培養・in vitro": {
        "keywords": [
            "co-culture", "coculture",
            "in vitro differentiation", "cell culture",
            "osteoclast differentiation", "osteoblast differentiation",
            "T cell activation assay", "cytotoxicity assay",
            "proliferation assay", "suppression assay",
        ],
        "applicability": {
            "NKT恒常性維持": "NKT細胞の増殖・生存シグナルの機能解析に有用",
            "NKTワクチン": "NKT-DC相互作用の解析やワクチン効果のin vitro評価に応用可能",
            "骨代謝研究": "破骨細胞・骨芽細胞分化に対するNKT由来因子の影響評価に有用",
        },
    },
    "臨床研究": {
        "keywords": [
            "clinical trial", "phase I", "phase II", "phase III",
            "patient cohort", "clinical study",
            "peripheral blood", "PBMC",
            "healthy donor", "patient sample",
            "biomarker", "prognosis",
        ],
        "applicability": {
            "NKTワクチン": "NKTワクチンの臨床応用データとして直接参考になる",
            "整形外科": "患者検体を用いた免疫学的バイオマーカーの研究に応用可能",
        },
    },
    "TCR解析": {
        "keywords": [
            "TCR repertoire", "TCR sequencing",
            "Vβ chain", "Vbeta", "CDR3",
            "TCR diversity", "clonotype",
            "TCR signaling",
        ],
        "applicability": {
            "NKT恒常性維持": "NKTのsemi-invariant TCRレパトアの多様性と恒常性維持の関係解明に有用",
            "NKTワクチン": "ワクチン応答におけるNKTクローン選択の評価に応用可能",
        },
    },
}


# ── Concept profiles ──────────────────────────────────────────────────

CONCEPT_PROFILES: dict[str, dict] = {
    "免疫恒常性": {
        "keywords": [
            "immune homeostasis", "homeostatic proliferation",
            "steady state", "immune regulation",
            "regulatory function", "immune tolerance",
            "self-renewal", "cell survival",
            "apoptosis resistance", "quiescence",
        ],
        "relevance": {
            "NKT恒常性維持": "NKT細胞の恒常性維持機構の理解に直結するコンセプト",
        },
    },
    "免疫-骨クロストーク": {
        "keywords": [
            "osteoimmunology", "immune bone",
            "bone immune", "skeletal immune",
            "osteoclast immune", "RANKL immune",
            "inflammatory bone loss", "immune-mediated bone",
        ],
        "relevance": {
            "骨代謝研究": "免疫細胞が骨代謝に与える影響という研究の中核コンセプト",
            "整形外科": "炎症性骨破壊や整形外科疾患の病態理解に重要",
        },
    },
    "組織常在免疫": {
        "keywords": [
            "tissue-resident", "tissue resident",
            "tissue residency", "tissue homing",
            "organ-specific", "local immunity",
            "niche", "microenvironment",
        ],
        "relevance": {
            "NKT恒常性維持": "組織常在NKTの維持メカニズムの理解に重要",
            "骨代謝研究": "骨髄ニッチにおけるNKTの役割理解に応用可能",
        },
    },
    "自然免疫-獲得免疫ブリッジ": {
        "keywords": [
            "innate-adaptive", "bridge", "innate adaptive",
            "innate-like", "innate like lymphocyte",
            "unconventional T cell", "bridging immunity",
        ],
        "relevance": {
            "NKT恒常性維持": "NKTのinnate-like T cellとしての特性理解に重要",
            "NKTワクチン": "NKTをブリッジとしたワクチン戦略の理論的基盤",
        },
    },
    "細胞治療・養子免疫療法": {
        "keywords": [
            "adoptive cell therapy", "cell therapy",
            "CAR-T", "CAR-NKT", "chimeric antigen",
            "ex vivo expansion", "GMP",
            "cell manufacturing",
        ],
        "relevance": {
            "NKTワクチン": "NKT細胞を用いた細胞治療の技術的・概念的枠組みとして直接関連",
        },
    },
    "サイトカインネットワーク": {
        "keywords": [
            "cytokine network", "cytokine milieu",
            "IL-4", "IFN-γ", "IFNγ", "IL-12",
            "IL-17", "IL-21", "cytokine storm",
            "Th1", "Th2", "cytokine bias",
        ],
        "relevance": {
            "NKT恒常性維持": "NKTのサイトカイン産生パターンと恒常性維持の関係理解に有用",
            "NKTワクチン": "ワクチン応答の免疫誘導方向（Th1/Th2）の制御に重要",
            "骨代謝研究": "炎症性サイトカインによる骨吸収制御の理解に応用可能",
        },
    },
    "脂質免疫学": {
        "keywords": [
            "lipid immunology", "lipid antigen",
            "CD1d", "lipid presentation",
            "glycolipid", "sphingolipid",
            "lipid raft", "lipid metabolism immune",
        ],
        "relevance": {
            "NKT恒常性維持": "NKTの抗原認識と恒常性維持における脂質環境の理解に重要",
            "NKTワクチン": "脂質抗原ベースのワクチン設計に直接関連するコンセプト",
        },
    },
    "骨リモデリング": {
        "keywords": [
            "bone remodeling", "bone turnover",
            "coupling", "osteoclast-osteoblast",
            "bone formation resorption",
            "remodeling cycle", "bone homeostasis",
        ],
        "relevance": {
            "骨代謝研究": "骨リモデリングのメカニズム理解という研究の基盤コンセプト",
            "整形外科": "手術後の骨治癒やインプラント周囲骨代謝の理解に重要",
        },
    },
}


# ── Topic scoring profiles (13 categories) ───────────────────────────

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


# ── Scored article result ─────────────────────────────────────────────

@dataclass
class ScoredArticle:
    paper: Paper
    total_score: float = 0.0
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    matched_methods: list[str] = field(default_factory=list)
    matched_concepts: list[str] = field(default_factory=list)
    lab_relevance: dict[str, float] = field(default_factory=dict)
    recommendation_reason: str = ""

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return "iNKT development"
        return max(self.topic_scores, key=self.topic_scores.get)

    @property
    def primary_lab_area(self) -> str:
        if not self.lab_relevance:
            return ""
        return max(self.lab_relevance, key=self.lab_relevance.get)


# ── Scorer ────────────────────────────────────────────────────────────

def _text_contains(text: str, keyword: str) -> bool:
    return bool(re.search(re.escape(keyword), text, re.IGNORECASE))


def _build_searchable_text(paper: Paper) -> str:
    return " ".join([
        paper.title, paper.abstract,
        " ".join(paper.keywords), " ".join(paper.mesh_terms),
    ])


class RelevanceScorer:

    TITLE_MULTIPLIER = 2.0
    SCORE_THRESHOLD = 0.15

    # Weights for final composite score
    W_TOPIC = 0.40
    W_METHOD = 0.25
    W_CONCEPT = 0.20
    W_LAB = 0.15

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        # 1. Topic scoring
        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_keyword_profile(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        topic_max = max(result.topic_scores.values()) if result.topic_scores else 0.0

        # 2. Method scoring
        method_scores: dict[str, float] = {}
        for method_name, profile in METHOD_PROFILES.items():
            score = self._score_keywords(full_text, profile["keywords"])
            if score > 0:
                method_scores[method_name] = score
                result.matched_methods.append(method_name)

        method_max = max(method_scores.values()) if method_scores else 0.0

        # 3. Concept scoring
        concept_scores: dict[str, float] = {}
        for concept_name, profile in CONCEPT_PROFILES.items():
            score = self._score_keywords(full_text, profile["keywords"])
            if score > 0:
                concept_scores[concept_name] = score
                result.matched_concepts.append(concept_name)

        concept_max = max(concept_scores.values()) if concept_scores else 0.0

        # 4. Lab research area scoring
        for area_name, area in LAB_RESEARCH_AREAS.items():
            score = self._score_keywords(full_text, area["keywords"])
            if score > 0:
                result.lab_relevance[area_name] = score

        lab_max = max(result.lab_relevance.values()) if result.lab_relevance else 0.0

        # Composite score
        result.total_score = min(
            self.W_TOPIC * topic_max
            + self.W_METHOD * method_max
            + self.W_CONCEPT * concept_max
            + self.W_LAB * lab_max,
            1.0,
        )

        # Boost: papers hitting multiple lab areas get a bonus
        if len(result.lab_relevance) >= 2:
            result.total_score = min(result.total_score * 1.2, 1.0)

        # Generate recommendation reason
        result.recommendation_reason = self._generate_reason(
            result, method_scores, concept_scores,
        )

        return result

    def _score_keyword_profile(
        self, paper: Paper, full_text: str, profile: dict,
    ) -> float:
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

    def _score_keywords(self, text: str, keywords: list[str]) -> float:
        hits = sum(1 for kw in keywords if _text_contains(text, kw))
        if hits == 0:
            return 0.0
        return min(hits * 0.2, 1.0)

    def _generate_reason(
        self,
        result: ScoredArticle,
        method_scores: dict[str, float],
        concept_scores: dict[str, float],
    ) -> str:
        parts = []

        # Lab area relevance
        if result.lab_relevance:
            top_areas = sorted(
                result.lab_relevance.items(), key=lambda x: x[1], reverse=True,
            )
            area_names = [a[0] for a in top_areas[:2]]
            parts.append(f"研究テーマ関連: {', '.join(area_names)}")

        # Method applicability
        if result.matched_methods:
            method_details = []
            for method_name in result.matched_methods[:2]:
                profile = METHOD_PROFILES[method_name]
                for area_name in result.lab_relevance:
                    if area_name in profile.get("applicability", {}):
                        method_details.append(
                            f"{method_name} → {profile['applicability'][area_name]}"
                        )
                        break
                else:
                    method_details.append(method_name)

            if method_details:
                parts.append(f"手法: {' / '.join(method_details)}")

        # Concept connections
        if result.matched_concepts:
            concept_details = []
            for concept_name in result.matched_concepts[:2]:
                profile = CONCEPT_PROFILES[concept_name]
                for area_name in result.lab_relevance:
                    if area_name in profile.get("relevance", {}):
                        concept_details.append(
                            f"{concept_name} — {profile['relevance'][area_name]}"
                        )
                        break
                else:
                    concept_details.append(concept_name)

            if concept_details:
                parts.append(f"コンセプト: {' / '.join(concept_details)}")

        if not parts:
            if result.matched_topics:
                parts.append(f"NKT研究トピック: {', '.join(result.matched_topics[:3])}")
            else:
                parts.append("NKT細胞関連論文")

        return "\n".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(
                f"Scored {len(scored)} papers. "
                f"Top score: {scored[0].total_score:.2f}"
            )
        return scored
