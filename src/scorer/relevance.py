"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Additionally scores papers on two dimensions:
  - Method: experimental techniques applicable to the lab's work
  - Concept: research themes relevant to the lab's questions
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Lab method profiles ──────────────────────────────────────────────────

LAB_METHOD_PROFILES: dict[str, dict] = {
    "フローサイトメトリー": {
        "keywords": [
            "flow cytometry", "FACS", "CyTOF", "mass cytometry",
            "spectral flow cytometry", "cell sorting",
            "intracellular staining", "tetramer staining",
            "CD1d tetramer", "PBS-57",
        ],
        "lab_use": "NKT細胞サブセット解析・表面マーカー評価に応用可能",
    },
    "マウスモデル": {
        "keywords": [
            "mouse model", "knockout mice", "transgenic mice",
            "bone marrow chimera", "adoptive transfer",
            "conditional knockout", "Cre-lox", "Jα18",
            "CD1d knockout", "Vα14 transgenic",
        ],
        "lab_use": "NKT恒常性維持・骨代謝マウスモデルに応用可能",
    },
    "scRNA-seq / オミクス": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "CITE-seq",
            "spatial transcriptomics", "10x Genomics",
            "ATAC-seq", "ChIP-seq", "multiome",
            "trajectory analysis", "pseudotime",
        ],
        "lab_use": "NKT細胞の不均一性・分化過程の解析に応用可能",
    },
    "骨解析手法": {
        "keywords": [
            "micro-CT", "histomorphometry", "DEXA",
            "bone mineral density", "TRAP staining",
            "alkaline phosphatase staining", "calcein labeling",
            "mechanical testing", "bone strength",
        ],
        "lab_use": "整形外科・骨代謝研究のアウトカム評価に直結",
    },
    "α-GalCer / 脂質抗原": {
        "keywords": [
            "alpha-GalCer", "α-GalCer", "KRN7000",
            "glycolipid antigen", "CD1d loading",
            "lipid antigen presentation", "αGC-loaded DC",
        ],
        "lab_use": "NKTワクチン・NKT活性化プロトコルに直結",
    },
    "CAR-NKT / 細胞工学": {
        "keywords": [
            "CAR-NKT", "CAR NKT", "chimeric antigen receptor NKT",
            "NKT cell engineering", "lentiviral transduction NKT",
            "NKT cell expansion", "ex vivo expansion",
        ],
        "lab_use": "NKT細胞治療・ワクチンへの応用技術",
    },
    "共培養 / in vitro": {
        "keywords": [
            "co-culture", "coculture", "in vitro stimulation",
            "DC-NKT coculture", "B cell NKT coculture",
            "antigen presentation assay", "killing assay",
            "cytotoxicity assay", "suppression assay",
        ],
        "lab_use": "NKT-B cell・DC-NKT相互作用の解析に応用可能",
    },
    "イメージング": {
        "keywords": [
            "confocal microscopy", "two-photon microscopy",
            "intravital imaging", "immunofluorescence",
            "immunohistochemistry", "tissue clearing",
            "live imaging", "in vivo imaging",
        ],
        "lab_use": "NKT細胞の組織内局在・細胞間相互作用の可視化に応用",
    },
}


# ── Lab concept profiles ─────────────────────────────────────────────────

LAB_CONCEPT_PROFILES: dict[str, dict] = {
    "NKT恒常性維持": {
        "keywords": [
            "NKT homeostasis", "iNKT homeostasis", "NKT maintenance",
            "NKT survival", "NKT turnover", "NKT proliferation",
            "tissue-resident NKT", "NKT cell number",
            "NKT steady state", "NKT cell death",
            "IL-7 NKT", "IL-15 NKT", "NKT apoptosis",
            "iNKT cell proliferation", "iNKT cell accumulation",
            "iNKT cell growth", "iNKT cell imprinting",
            "mucosal homeostasis", "immune homeostasis",
            "reductions in iNKT", "colonic iNKT",
            "stromal niche", "niche",
        ],
        "relevance": "NKT細胞の末梢での維持機構 — 当ラボのコアテーマに直結",
    },
    "NKTワクチン・免疫療法": {
        "keywords": [
            "NKT vaccine", "NKT adjuvant", "NKT immunotherapy",
            "NKT anti-tumor", "NKT cancer therapy",
            "DC pulse", "dendritic cell vaccine",
            "NKT cell therapy", "NKT clinical trial",
            "NKT tumor rejection",
            "iNKT cell agonist", "vaccine adjuvant",
            "dual adjuvant", "vaccine design",
            "subunit vaccine",
        ],
        "relevance": "NKTワクチン開発 — 臨床応用の基盤研究",
    },
    "NKT-B cell相互作用": {
        "keywords": [
            "NKT B cell", "NKT follicular", "NKT germinal center",
            "NKT antibody", "B cell help NKT", "NKT-B interaction",
            "CXCR6", "CXCL16", "NKT marginal zone B",
        ],
        "relevance": "NKTによるB cell制御 — 恒常性維持機能の重要な側面",
    },
    "骨免疫学・骨代謝": {
        "keywords": [
            "osteoimmunology", "osteoclast", "osteoblast",
            "RANKL", "OPG", "bone remodeling",
            "bone resorption", "bone formation",
            "osteoporosis", "fracture healing",
            "bone marrow niche", "bone metabolism",
        ],
        "relevance": "骨免疫学 — 整形外科研究とNKT研究の交差点",
    },
    "免疫制御・自己寛容": {
        "keywords": [
            "immune regulation NKT", "NKT tolerance",
            "NKT regulatory", "NKT suppression",
            "B cell tolerance", "autoreactive B",
            "self-reactive", "immune homeostasis",
        ],
        "relevance": "NKTの免疫制御機能 — 恒常性維持の広義の文脈",
    },
    "胸腺発生・分化": {
        "keywords": [
            "NKT development", "thymic NKT", "NKT selection",
            "NKT maturation", "NKT differentiation",
            "NKT1 NKT2 NKT17", "PLZF", "NKT precursor",
        ],
        "relevance": "NKT発生・分化 — 恒常性維持の上流機構",
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
    matched_concepts: list[str] = field(default_factory=list)
    method_connections: list[str] = field(default_factory=list)
    concept_connections: list[str] = field(default_factory=list)
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
    CONCEPT_BONUS = 0.15

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        base_score = max(result.topic_scores.values()) if result.topic_scores else 0.0

        method_score = self._score_methods(full_text, result)
        concept_score = self._score_concepts(full_text, result)

        result.total_score = min(
            base_score + method_score * self.METHOD_BONUS + concept_score * self.CONCEPT_BONUS,
            1.0,
        )

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

    def _score_methods(self, full_text: str, result: ScoredArticle) -> float:
        hits = 0
        for method_name, profile in LAB_METHOD_PROFILES.items():
            matched_kw = [
                kw for kw in profile["keywords"]
                if _text_contains(full_text, kw)
            ]
            if matched_kw:
                hits += 1
                result.matched_methods.append(method_name)
                result.method_connections.append(
                    f"[{method_name}] {profile['lab_use']}"
                )
        return min(hits, 3)

    def _score_concepts(self, full_text: str, result: ScoredArticle) -> float:
        hits = 0
        for concept_name, profile in LAB_CONCEPT_PROFILES.items():
            matched_kw = [
                kw for kw in profile["keywords"]
                if _text_contains(full_text, kw)
            ]
            if matched_kw:
                hits += 1
                result.matched_concepts.append(concept_name)
                result.concept_connections.append(
                    f"[{concept_name}] {profile['relevance']}"
                )
        return min(hits, 3)

    def _generate_reason(self, result: ScoredArticle) -> str:
        parts = []

        if result.concept_connections:
            parts.append("【コンセプト】" + "；".join(
                c.split("] ")[1] for c in result.concept_connections[:2]
            ))

        if result.method_connections:
            parts.append("【手法】" + "；".join(
                m.split("] ")[1] for m in result.method_connections[:2]
            ))

        if not parts:
            if result.matched_topics:
                return f"NKT関連（{', '.join(result.matched_topics[:2])}）"
            return "NKT関連論文"

        return " / ".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
