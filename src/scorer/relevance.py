"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests and classifies them
according to the Notion database Topics:
  iNKT development, NKT-B cell, Osteoimmunology, Autoimmunity / SLE,
  Metabolism, Tumor immunity, Infection, Methods / Omics,
  Thymus / development, B cell tolerance, Cytokines (IL-4/IFNγ),
  TCR repertoire, scRNA-seq / spatial

Papers are ranked by relevance to 4 research pillars and recommended
based on both conceptual connections and methodological applicability:
  1. NKTの恒常性維持機能 (NKT homeostasis / regulatory function)
  2. NKTワクチン (NKT vaccine / immunotherapy)
  3. 整形外科 (Orthopedic surgery)
  4. 骨代謝研究 (Bone metabolism research)
"""

import logging
import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper

logger = logging.getLogger(__name__)


# ── Research pillars (our lab's 4 core areas) ──────────────────────────

RESEARCH_PILLARS: dict[str, dict] = {
    "NKT恒常性維持": {
        "label_en": "NKT homeostasis / regulatory function",
        "topics": [
            "iNKT development", "Thymus / development", "NKT-B cell",
            "B cell tolerance", "Cytokines (IL-4/IFNγ)", "TCR repertoire",
        ],
        "concept_keywords": [
            "homeostasis", "maintenance", "survival", "turnover",
            "steady state", "tissue-resident", "tissue resident",
            "peripheral maintenance", "cell fate", "cell death",
            "apoptosis", "proliferation", "self-renewal",
            "regulatory function", "immune regulation",
            "tolerance", "immune homeostasis",
            "NKT subset", "NKT1", "NKT2", "NKT17",
            "PLZF", "T-bet", "RORγt", "GATA3",
        ],
    },
    "NKTワクチン": {
        "label_en": "NKT vaccine / immunotherapy",
        "topics": [
            "Tumor immunity", "Infection",
        ],
        "concept_keywords": [
            "vaccine", "vaccination", "adjuvant", "immunotherapy",
            "cell therapy", "adoptive transfer", "CAR",
            "chimeric antigen receptor", "dendritic cell",
            "antigen presentation", "α-GalCer", "alpha-GalCer",
            "clinical trial", "phase I", "phase II",
            "ex vivo expansion", "GMP", "cell manufacturing",
            "anti-tumor", "antitumor", "tumor rejection",
            "immune checkpoint", "PD-1", "PD-L1",
            "combination therapy", "prime-boost",
        ],
    },
    "整形外科": {
        "label_en": "Orthopedic surgery",
        "topics": [
            "Osteoimmunology",
        ],
        "concept_keywords": [
            "orthopedic", "orthopaedic", "fracture", "fracture healing",
            "bone repair", "arthroplasty", "joint replacement",
            "spinal fusion", "spine", "vertebral",
            "osteoarthritis", "rheumatoid arthritis",
            "synovial", "synovitis", "cartilage",
            "ligament", "tendon", "musculoskeletal",
            "surgical", "implant", "prosthesis",
            "postoperative", "perioperative",
            "inflammation joint", "joint inflammation",
        ],
    },
    "骨代謝研究": {
        "label_en": "Bone metabolism research",
        "topics": [
            "Osteoimmunology", "Metabolism",
        ],
        "concept_keywords": [
            "bone metabolism", "bone remodeling", "bone resorption",
            "bone formation", "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "RANK", "OPG", "osteoprotegerin",
            "bone mineral density", "osteoporosis",
            "calcium metabolism", "phosphate metabolism",
            "vitamin D", "PTH", "parathyroid",
            "Wnt signaling", "BMP", "sclerostin", "DKK1",
            "bone marrow", "bone marrow niche",
            "mesenchymal stem cell", "MSC",
            "bone immune", "osteoimmunology",
        ],
    },
}


# ── Method profiles (experimental approaches) ─────────────────────────

METHOD_PROFILES: dict[str, list[str]] = {
    "scRNA-seq / single-cell": [
        "scRNA-seq", "single-cell RNA", "single cell RNA",
        "10x Genomics", "Drop-seq", "Smart-seq",
        "CITE-seq", "multiome", "single-cell ATAC",
        "single cell analysis", "single-cell transcriptomics",
        "cell clustering", "UMAP", "t-SNE",
        "trajectory analysis", "pseudotime",
        "Seurat", "Scanpy",
    ],
    "spatial transcriptomics": [
        "spatial transcriptomics", "Visium", "MERFISH",
        "seqFISH", "CODEX", "spatial proteomics",
        "spatial omics", "tissue mapping",
        "in situ sequencing", "slide-seq",
    ],
    "flow cytometry / CyTOF": [
        "flow cytometry", "FACS", "CyTOF", "mass cytometry",
        "spectral flow", "spectral cytometry",
        "multicolor", "multiparameter",
        "tetramer", "CD1d tetramer", "PBS-57",
    ],
    "in vivo model": [
        "knockout mouse", "knock-out mouse", "KO mice",
        "conditional knockout", "Cre-lox", "floxed",
        "transgenic mouse", "transgenic mice",
        "bone marrow chimera", "adoptive transfer",
        "parabiosis", "fate mapping", "lineage tracing",
        "Jα18", "CD1d-/-", "CD1d KO",
        "mouse model", "murine model",
        "in vivo imaging", "intravital",
    ],
    "CRISPR / gene editing": [
        "CRISPR", "Cas9", "guide RNA", "sgRNA",
        "gene editing", "genome editing",
        "CRISPR screen", "knockout screen",
        "base editing", "prime editing",
    ],
    "ATAC-seq / epigenomics": [
        "ATAC-seq", "ChIP-seq", "CUT&Tag", "CUT&RUN",
        "histone modification", "chromatin accessibility",
        "epigenomic", "epigenetic profiling",
        "DNA methylation", "bisulfite",
    ],
    "proteomics / metabolomics": [
        "proteomics", "mass spectrometry", "LC-MS",
        "metabolomics", "lipidomics",
        "phosphoproteomics", "glycoproteomics",
    ],
    "clinical / translational": [
        "clinical trial", "phase I", "phase II", "phase III",
        "patient cohort", "patient sample",
        "PBMC", "peripheral blood",
        "biomarker", "prognosis", "diagnosis",
        "translational", "bedside",
    ],
    "bioinformatics / computational": [
        "machine learning", "deep learning",
        "network analysis", "pathway analysis",
        "gene signature", "deconvolution",
        "bulk RNA-seq", "transcriptome",
        "meta-analysis", "systematic review",
        "bioinformatics pipeline",
    ],
    "imaging": [
        "confocal microscopy", "two-photon",
        "multiplex imaging", "immunofluorescence",
        "histology", "immunohistochemistry", "IHC",
        "electron microscopy", "micro-CT", "μCT",
    ],
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
    recommendation_reason: str = ""
    matched_pillars: list[str] = field(default_factory=list)
    pillar_reasons: dict[str, str] = field(default_factory=dict)
    matched_methods: list[str] = field(default_factory=list)
    method_relevance: str = ""

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return "iNKT development"
        return max(self.topic_scores, key=self.topic_scores.get)

    @property
    def primary_pillar(self) -> str:
        if not self.matched_pillars:
            return ""
        return self.matched_pillars[0]


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

        # 1. Topic scoring (existing logic)
        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        result.total_score = max(result.topic_scores.values()) if result.topic_scores else 0.0

        # 2. Method detection
        result.matched_methods = self._detect_methods(full_text)

        # 3. Research pillar mapping
        self._map_to_pillars(result, full_text)

        # 4. Generate recommendation with method + concept reasoning
        result.recommendation_reason = self._generate_reason(result)
        result.method_relevance = self._generate_method_relevance(result)

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
        """Detect experimental methods used in the paper."""
        methods = []
        for method_name, keywords in METHOD_PROFILES.items():
            hits = sum(1 for kw in keywords if _text_contains(full_text, kw))
            if hits >= 2:
                methods.append(method_name)
        return methods

    def _map_to_pillars(self, result: ScoredArticle, full_text: str) -> None:
        """Map scored article to the lab's 4 research pillars."""
        pillar_scores: list[tuple[str, float, str]] = []

        for pillar_name, pillar in RESEARCH_PILLARS.items():
            # Score from matched topics
            topic_score = 0.0
            for topic in pillar["topics"]:
                ts = result.topic_scores.get(topic, 0.0)
                if ts >= self.SCORE_THRESHOLD:
                    topic_score = max(topic_score, ts)

            # Score from concept keywords
            concept_hits = [
                kw for kw in pillar["concept_keywords"]
                if _text_contains(full_text, kw)
            ]
            concept_score = min(len(concept_hits) * 0.08, 0.5)

            combined = max(topic_score, concept_score)
            if combined >= self.SCORE_THRESHOLD:
                reason = self._build_pillar_reason(
                    pillar_name, pillar, result, concept_hits,
                )
                pillar_scores.append((pillar_name, combined, reason))

        # Sort by score descending
        pillar_scores.sort(key=lambda x: x[1], reverse=True)
        for name, _score, reason in pillar_scores:
            result.matched_pillars.append(name)
            result.pillar_reasons[name] = reason

    def _build_pillar_reason(
        self,
        pillar_name: str,
        pillar: dict,
        result: ScoredArticle,
        concept_hits: list[str],
    ) -> str:
        """Build a concise Japanese reason for why this paper relates to a pillar."""
        parts = []

        # Concept connection
        if concept_hits:
            top_concepts = concept_hits[:3]
            parts.append(f"コンセプト: {', '.join(top_concepts)}")

        # Topic connection
        related_topics = [
            t for t in pillar["topics"]
            if result.topic_scores.get(t, 0) >= self.SCORE_THRESHOLD
        ]
        if related_topics:
            parts.append(f"トピック: {', '.join(related_topics)}")

        # Method connection (suggest applicability)
        if result.matched_methods:
            parts.append(f"手法: {', '.join(result.matched_methods)}")

        return " | ".join(parts) if parts else pillar_name

    def _generate_reason(self, result: ScoredArticle) -> str:
        """Generate a detailed recommendation reason in Japanese."""
        parts = []

        # Research pillar relevance
        if result.matched_pillars:
            pillar_labels = {
                "NKT恒常性維持": "NKT恒常性維持機能",
                "NKTワクチン": "NKTワクチン研究",
                "整形外科": "整形外科研究",
                "骨代謝研究": "骨代謝研究",
            }
            labels = [pillar_labels.get(p, p) for p in result.matched_pillars]
            parts.append(f"【研究との関連】{' / '.join(labels)}")

            # Add the most relevant pillar's detailed reason
            top_pillar = result.matched_pillars[0]
            if top_pillar in result.pillar_reasons:
                parts.append(f"  → {result.pillar_reasons[top_pillar]}")

        # Method applicability
        if result.matched_methods:
            parts.append(f"【手法】{', '.join(result.matched_methods)}")

        # Topic classification
        if result.matched_topics:
            parts.append(f"【トピック】{', '.join(result.matched_topics)}")

        if not parts:
            return "NKT細胞関連"

        return "\n".join(parts)

    def _generate_method_relevance(self, result: ScoredArticle) -> str:
        """Generate suggestion for how this paper's methods could help our research."""
        if not result.matched_methods:
            return ""

        suggestions = []
        methods = set(result.matched_methods)
        pillars = set(result.matched_pillars)

        if "scRNA-seq / single-cell" in methods:
            if pillars & {"NKT恒常性維持"}:
                suggestions.append(
                    "scRNA-seqによるNKTサブセット解析は"
                    "恒常性維持メカニズムの解明に応用可能"
                )
            elif pillars & {"骨代謝研究", "整形外科"}:
                suggestions.append(
                    "scRNA-seqによる骨髄微小環境の解析手法を"
                    "骨代謝研究に転用できる可能性"
                )
            else:
                suggestions.append(
                    "scRNA-seq解析パイプラインは"
                    "当研究室のNKT研究に応用可能"
                )

        if "spatial transcriptomics" in methods:
            suggestions.append(
                "空間トランスクリプトーム解析は組織内NKT細胞の"
                "局在と機能の関連解明に有用"
            )

        if "in vivo model" in methods:
            if pillars & {"NKT恒常性維持"}:
                suggestions.append(
                    "マウスモデル・実験系がNKT恒常性研究に参考になる"
                )
            elif pillars & {"骨代謝研究", "整形外科"}:
                suggestions.append(
                    "in vivoモデルが骨免疫・整形外科研究に参考になる"
                )

        if "flow cytometry / CyTOF" in methods:
            suggestions.append(
                "フローサイトメトリー/CyTOFパネルが"
                "NKT解析に参考になる"
            )

        if "CRISPR / gene editing" in methods:
            suggestions.append(
                "遺伝子編集手法がNKT機能解析に応用できる可能性"
            )

        if "clinical / translational" in methods:
            if pillars & {"NKTワクチン"}:
                suggestions.append(
                    "臨床プロトコル・バイオマーカーが"
                    "NKTワクチン臨床応用の参考になる"
                )
            elif pillars & {"整形外科"}:
                suggestions.append(
                    "臨床データが整形外科領域の"
                    "免疫学的アプローチの参考になる"
                )

        if "imaging" in methods:
            if pillars & {"骨代謝研究", "整形外科"}:
                suggestions.append(
                    "イメージング手法（micro-CT等）が"
                    "骨代謝評価に参考になる"
                )

        return " / ".join(suggestions) if suggestions else ""

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        """Score all papers and rank by relevance.

        Ranking priority:
        1. Papers matching research pillars with high topic scores
        2. Papers with method applicability to our research
        3. General NKT relevance
        """
        scored = [self.score_paper(p) for p in papers]

        def _sort_key(s: ScoredArticle) -> tuple:
            # Boost: number of research pillars matched (max 4)
            pillar_boost = len(s.matched_pillars) * 0.15
            # Boost: method applicability
            method_boost = 0.05 if s.method_relevance else 0.0
            return (s.total_score + pillar_boost + method_boost, s.total_score)

        scored.sort(key=_sort_key, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
