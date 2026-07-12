"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Core research areas (boosted scoring):
  1. NKT homeostasis (iNKT development)
  2. NKT vaccines (Tumor immunity)
  3. Orthopedics / Bone metabolism (Osteoimmunology)
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)

CORE_RESEARCH_TOPICS = {
    "iNKT development",
    "Thymus / development",
    "NKT-B cell",
    "B cell tolerance",
    "Tumor immunity",
    "Osteoimmunology",
}

CORE_BOOST = 1.3

ENKTL_INDICATORS = [
    "extranodal natural killer/T-cell lymphoma",
    "extranodal NK/T-cell lymphoma",
    "extranodal natural killer T-cell lymphoma",
    "ENKTL",
    "nasal-type NK/T",
    "nasal type NK/T",
    "NK/T-cell lymphoma",
    "NK/T cell lymphoma",
]


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
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    recommendation_reason: str = ""
    is_enktl: bool = False
    application_points: list[str] = field(default_factory=list)

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

    def _detect_enktl(self, paper: Paper) -> bool:
        text = f"{paper.title} {paper.abstract}"
        for indicator in ENKTL_INDICATORS:
            if _text_contains(text, indicator):
                return True
        return False

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        result.is_enktl = self._detect_enktl(paper)

        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            if topic_name in CORE_RESEARCH_TOPICS:
                score = min(score * CORE_BOOST, 1.0)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        result.total_score = max(result.topic_scores.values()) if result.topic_scores else 0.0

        if result.is_enktl:
            result.total_score *= 0.1

        result.recommendation_reason = self._generate_reason(result)
        result.application_points = self._generate_application_points(result)
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

    def _generate_reason(self, result: ScoredArticle) -> str:
        if result.is_enktl:
            return "ENKTL (節外性NK/Tリンパ腫) — iNKTとは異なる疾患"
        if result.matched_topics:
            return f"Topics: {', '.join(result.matched_topics)}"
        return "NKT cell related"

    def _generate_application_points(self, result: ScoredArticle) -> list[str]:
        points = []
        topics = set(result.matched_topics)
        paper = result.paper
        full_text = _build_searchable_text(paper)

        if result.is_enktl:
            points.append("ENKTL論文: iNKT細胞研究とは直接関連しないが、NKT名称を含むため検索にヒット")
            return points

        if topics & {"iNKT development", "Thymus / development"}:
            points.append("NKT恒常性: iNKT細胞の発生・分化・恒常性維持機構に関連")
        if "Tumor immunity" in topics:
            points.append("NKTワクチン: NKT細胞の抗腫瘍免疫・細胞療法に関連")
        if "Osteoimmunology" in topics:
            points.append("骨代謝・整形外科: 骨免疫学の知見、骨代謝との接点")
        if "NKT-B cell" in topics or "B cell tolerance" in topics:
            points.append("NKT-B細胞相互作用: B細胞トレランス・抗体応答の制御に関連")
        if "Metabolism" in topics:
            points.append("代謝: NKT細胞の代謝制御・脂質代謝との関連")
        if topics & {"Methods / Omics", "scRNA-seq / spatial"}:
            points.append("手法: 新規実験手法・オミクス解析技術の参考に")
        if topics & {"Cytokines (IL-4/IFNγ)", "TCR repertoire"}:
            points.append("基礎メカニズム: サイトカイン産生やTCRレパトア解析の知見")

        method_keywords = [
            ("CAR-NKT", "CAR-iNKT細胞作製技術"),
            ("CAR-iNKT", "CAR-iNKT細胞作製技術"),
            ("chimeric antigen receptor", "CAR技術"),
            ("adoptive transfer", "養子移入プロトコル"),
            ("ex vivo expansion", "ex vivo拡大培養法"),
            ("α-GalCer", "α-GalCer投与戦略"),
            ("alpha-GalCer", "α-GalCer投与戦略"),
            ("scRNA-seq", "シングルセルRNA-seq解析"),
            ("CITE-seq", "CITE-seq解析"),
            ("spatial transcriptomics", "空間トランスクリプトミクス"),
            ("CyTOF", "マスサイトメトリー"),
            ("CIBERSORT", "免疫浸潤解析(CIBERSORT)"),
            ("flow cytometry", "フローサイトメトリー"),
            ("bone marrow", "骨髄解析"),
            ("osteoclast", "破骨細胞関連手法"),
            ("osteoblast", "骨芽細胞関連手法"),
        ]

        matched_methods = []
        for keyword, description in method_keywords:
            if _text_contains(full_text, keyword) and description not in matched_methods:
                matched_methods.append(description)

        if matched_methods:
            points.append(f"注目手法: {', '.join(matched_methods[:4])}")

        if not points:
            points.append("NKT細胞研究に関連（一般的な関連性）")

        return points

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: (-int(not x.is_enktl), -x.total_score))
        if scored:
            inkt_papers = [s for s in scored if not s.is_enktl]
            enktl_papers = [s for s in scored if s.is_enktl]
            logger.info(
                f"Scored {len(scored)} papers: "
                f"{len(inkt_papers)} iNKT-related, {len(enktl_papers)} ENKTL. "
                f"Top score: {scored[0].total_score:.2f}"
            )
        return scored
