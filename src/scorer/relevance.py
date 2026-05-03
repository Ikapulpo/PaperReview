"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Also evaluates methods/techniques and conceptual relevance to generate
specific recommendations on how papers can inform the lab's research
(NKT homeostasis, NKT vaccine, orthopedics, bone metabolism).
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Lab research themes for concept bridging ──────────────────────────────

LAB_RESEARCH_THEMES = {
    "NKT恒常性維持": {
        "description": "NKT細胞の恒常性維持機構の解明",
        "connect_keywords": [
            "homeostasis", "maintenance", "survival", "turnover",
            "tissue-resident", "steady state", "proliferation",
            "IL-7", "IL-15", "PLZF", "maturation",
            "NKT1", "NKT2", "NKT17", "differentiation",
            "emigration", "peripheral maintenance",
        ],
    },
    "NKTワクチン": {
        "description": "NKT細胞を活用したワクチン・細胞治療の開発",
        "connect_keywords": [
            "vaccine", "adjuvant", "α-GalCer", "alpha-GalCer",
            "dendritic cell", "antigen presentation", "CD1d",
            "cell therapy", "CAR-NKT", "adoptive transfer",
            "expansion", "activation", "clinical trial",
            "immunotherapy", "tumor rejection", "anti-tumor",
        ],
    },
    "整形外科・骨代謝": {
        "description": "骨代謝・整形外科領域とNKT細胞の接点",
        "connect_keywords": [
            "bone", "osteoclast", "osteoblast", "RANKL", "OPG",
            "fracture", "osteoporosis", "bone remodeling",
            "arthritis", "joint", "cartilage", "synovial",
            "bone marrow", "inflammation bone", "steroid",
            "glucocorticoid", "bone loss", "bone healing",
            "orthopedic", "orthopaedic", "arthroplasty",
            "musculoskeletal", "bone mineral density",
        ],
    },
}

# ── Method profiles for technique-based scoring ───────────────────────────

METHOD_PROFILES: dict[str, dict] = {
    "Flow cytometry / CyTOF": {
        "keywords": [
            "flow cytometry", "FACS", "CyTOF", "mass cytometry",
            "spectral flow", "intracellular staining",
            "surface marker", "CD1d tetramer", "PBS-57",
        ],
        "lab_relevance": "NKTのサブセット解析・恒常性維持の定量評価に直接応用可能",
    },
    "scRNA-seq / Multiomics": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "CITE-seq",
            "multiome", "ATAC-seq", "spatial transcriptomics",
            "trajectory analysis", "pseudotime",
        ],
        "lab_relevance": "NKT分化・恒常性の分子機構解明、新規マーカー同定に有用",
    },
    "In vivo mouse model": {
        "keywords": [
            "knockout", "conditional knockout", "Cre-lox",
            "bone marrow chimera", "adoptive transfer",
            "Jα18", "CD1d-/-", "transgenic",
            "in vivo", "mouse model",
        ],
        "lab_relevance": "NKTの生体内機能解析、恒常性メカニズム解明のモデルとして参考",
    },
    "Bone/Joint analysis": {
        "keywords": [
            "micro-CT", "μCT", "bone histomorphometry",
            "TRAP staining", "ALP staining", "DXA",
            "bone mineral density", "biomechanical testing",
            "synovial analysis", "joint scoring",
        ],
        "lab_relevance": "骨代謝研究の評価手法として直接応用可能",
    },
    "Cell culture / Expansion": {
        "keywords": [
            "NKT expansion", "NKT culture", "in vitro expansion",
            "cell line", "co-culture", "stimulation protocol",
            "α-GalCer pulse", "DC loading",
        ],
        "lab_relevance": "NKTワクチン開発における細胞調製・拡大培養法として参考",
    },
    "Clinical / Translational": {
        "keywords": [
            "clinical trial", "patient", "phase I", "phase II",
            "clinical study", "translational", "human NKT",
            "peripheral blood", "PBMC", "healthy donor",
        ],
        "lab_relevance": "NKTワクチンのヒトへのトランスレーション戦略として重要",
    },
    "Imaging / Spatial": {
        "keywords": [
            "confocal", "two-photon", "intravital imaging",
            "immunofluorescence", "immunohistochemistry",
            "spatial analysis", "tissue clearing",
        ],
        "lab_relevance": "NKTの組織内局在・骨髄内動態の可視化手法として有用",
    },
    "Bioinformatics / Computational": {
        "keywords": [
            "bioinformatics", "machine learning", "network analysis",
            "gene signature", "pathway analysis", "GSEA",
            "TCR analysis", "clonotype", "computational",
        ],
        "lab_relevance": "大規模データからのNKT恒常性関連遺伝子の同定に応用可能",
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
    topic_scores: dict[str, float] = field(default_factory=dict)
    matched_topics: list[str] = field(default_factory=list)
    matched_methods: list[str] = field(default_factory=list)
    concept_bridges: list[str] = field(default_factory=list)
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
    METHOD_BONUS = 0.08  # bonus per matched method

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        # Topic scoring
        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        # Method detection
        result.matched_methods = self._detect_methods(full_text)

        # Concept bridging
        result.concept_bridges = self._build_concept_bridges(full_text, result)

        # Total score: topic max + method bonus
        topic_max = max(result.topic_scores.values()) if result.topic_scores else 0.0
        method_bonus = min(len(result.matched_methods) * self.METHOD_BONUS, 0.2)
        concept_bonus = min(len(result.concept_bridges) * 0.05, 0.15)
        result.total_score = min(topic_max + method_bonus + concept_bonus, 1.0)

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
        """Detect experimental methods/techniques used in the paper."""
        matched = []
        for method_name, profile in METHOD_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    matched.append(method_name)
                    break
        return matched

    def _build_concept_bridges(
        self, full_text: str, result: ScoredArticle
    ) -> list[str]:
        """Generate concept bridges explaining how this paper connects to lab research."""
        bridges = []
        for theme_name, theme in LAB_RESEARCH_THEMES.items():
            hit_keywords = [
                kw for kw in theme["connect_keywords"]
                if _text_contains(full_text, kw)
            ]
            if len(hit_keywords) >= 2:
                bridge = self._format_bridge(
                    theme_name, theme["description"],
                    hit_keywords, result.matched_methods,
                )
                bridges.append(bridge)
        return bridges

    def _format_bridge(
        self,
        theme_name: str,
        theme_desc: str,
        hit_keywords: list[str],
        methods: list[str],
    ) -> str:
        """Format a concept bridge as a short recommendation string."""
        kw_sample = ", ".join(hit_keywords[:4])
        base = f"[{theme_name}] {theme_desc}に関連（{kw_sample}）"
        if methods:
            method_relevance = []
            for m in methods:
                lab_rel = METHOD_PROFILES[m]["lab_relevance"]
                method_relevance.append(f"{m}: {lab_rel}")
            base += f" | 手法: {'; '.join(method_relevance[:2])}"
        return base

    def _generate_reason(self, result: ScoredArticle) -> str:
        """Generate a specific recommendation reason combining topics, methods, concepts."""
        parts = []

        if result.matched_topics:
            parts.append(f"トピック: {', '.join(result.matched_topics)}")

        if result.matched_methods:
            method_notes = []
            for m in result.matched_methods[:3]:
                method_notes.append(
                    f"{m}（{METHOD_PROFILES[m]['lab_relevance'][:30]}…）"
                )
            parts.append(f"手法: {'; '.join(method_notes)}")

        if result.concept_bridges:
            parts.append(f"コンセプト接点: {len(result.concept_bridges)}件")

        if not parts:
            return "NKT cell関連"

        return " | ".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
