"""Relevance scoring engine for NKT cell papers.

Scores papers against the lab's research interests across three dimensions:
  1. Topic classification (13 topics)
  2. Experimental method detection
  3. Research area connection (4 lab areas)

Lab research areas:
  - NKTの恒常性維持機能
  - NKTワクチン
  - 整形外科
  - 骨代謝研究
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


# ── Experimental method profiles ───────────────────────────────────────

METHOD_PROFILES: dict[str, dict] = {
    "フローサイトメトリー": {
        "keywords": [
            "flow cytometry", "FACS", "fluorescence-activated",
            "intracellular staining", "surface staining",
            "cell sorting", "gating strategy",
        ],
        "description": "NKT細胞のサブセット解析やfunctional assayに直接応用可能",
    },
    "マスサイトメトリー (CyTOF)": {
        "keywords": [
            "CyTOF", "mass cytometry", "metal-labeled",
            "heavy metal isotope",
        ],
        "description": "多パラメータ解析によるNKT細胞の包括的フェノタイピングに有用",
    },
    "シングルセル解析": {
        "keywords": [
            "scRNA-seq", "single-cell RNA", "single cell RNA",
            "CITE-seq", "ATAC-seq", "multiome",
            "10x Genomics", "droplet-based", "Smart-seq",
            "single-cell transcriptom", "single cell transcriptom",
        ],
        "description": "NKT細胞の不均一性やステート遷移の解析に活用可能",
    },
    "空間トランスクリプトーム": {
        "keywords": [
            "spatial transcriptomics", "Visium", "MERFISH",
            "seqFISH", "Slide-seq", "spatial omics",
            "in situ sequencing",
        ],
        "description": "組織内でのNKT細胞の局在・相互作用の解析に応用可能",
    },
    "in vivoモデル": {
        "keywords": [
            "knockout mouse", "knockout mice", "KO mice",
            "transgenic mouse", "transgenic mice",
            "adoptive transfer", "bone marrow chimera",
            "conditional knockout", "Cre-lox",
            "in vivo", "mouse model", "murine model",
        ],
        "description": "NKT細胞の機能解析や疾患モデルに活用可能",
    },
    "骨解析": {
        "keywords": [
            "micro-CT", "microCT", "micro CT",
            "histomorphometry", "bone histomorphometry",
            "TRAP staining", "DEXA", "DXA",
            "bone mineral density", "BMD measurement",
            "calcein labeling", "alizarin red",
            "bone volume", "BV/TV",
            "trabecular", "cortical bone analysis",
        ],
        "description": "骨代謝研究に直結する解析手法",
    },
    "細胞培養・拡大培養": {
        "keywords": [
            "cell expansion", "ex vivo expansion",
            "in vitro culture", "cell culture",
            "co-culture", "feeder cell",
            "cytokine stimulation", "cell activation",
            "NKT expansion", "NKT cell culture",
        ],
        "description": "NKTワクチン用の細胞調製・拡大培養プロトコルに応用可能",
    },
    "臨床試験・トランスレーショナル": {
        "keywords": [
            "clinical trial", "phase I", "phase II", "phase III",
            "patient", "clinical study", "translational",
            "GMP", "good manufacturing", "cell therapy product",
            "adoptive cell therapy", "cell-based therapy",
        ],
        "description": "NKTワクチンの臨床展開に直接参考になる知見",
    },
    "遺伝子操作・CRISPR": {
        "keywords": [
            "CRISPR", "Cas9", "gene editing",
            "gene knockout", "gene knockin",
            "shRNA", "siRNA", "retroviral transduction",
            "lentiviral", "CAR construct",
        ],
        "description": "NKT細胞の遺伝子改変・CAR-NKT作製に応用可能",
    },
    "イメージング": {
        "keywords": [
            "confocal", "two-photon", "intravital imaging",
            "immunofluorescence", "immunohistochemistry",
            "live imaging", "multiphoton",
            "fluorescence microscopy",
        ],
        "description": "NKT細胞の組織内動態や骨組織の可視化に応用可能",
    },
    "バイオインフォマティクス": {
        "keywords": [
            "bioinformatics", "computational analysis",
            "machine learning", "deep learning",
            "network analysis", "pathway analysis",
            "gene signature", "trajectory analysis",
            "pseudotime", "clustering analysis",
        ],
        "description": "NKT関連のオミクスデータ解析に活用可能",
    },
    "機能アッセイ": {
        "keywords": [
            "cytotoxicity assay", "killing assay",
            "ELISA", "ELISpot", "cytokine bead array",
            "chromium release", "lactate dehydrogenase",
            "suppression assay", "proliferation assay",
        ],
        "description": "NKT細胞のエフェクター機能評価に活用可能",
    },
    "DC負荷・ワクチン調製": {
        "keywords": [
            "dendritic cell loading", "DC pulsing",
            "antigen-loaded DC", "DC vaccine",
            "α-GalCer-loaded", "alpha-GalCer-loaded",
            "GalCer-pulsed", "lipid-loaded DC",
            "DC maturation", "monocyte-derived DC",
        ],
        "description": "NKTワクチンにおけるDC調製プロトコルに直接応用可能",
    },
}


# ── Lab research areas ─────────────────────────────────────────────────

LAB_RESEARCH_AREAS: dict[str, dict] = {
    "NKT恒常性維持": {
        "primary": [
            "NKT homeostasis", "iNKT homeostasis",
            "NKT maintenance", "NKT survival",
            "NKT cell turnover", "NKT proliferation",
            "tissue-resident NKT", "tissue resident NKT",
            "NKT steady state", "NKT cell number",
            "NKT cell pool", "NKT cell longevity",
        ],
        "secondary": [
            "homeostatic proliferation", "cell survival signal",
            "IL-7", "IL-15", "IL-7R", "IL-15R",
            "Bcl-2", "Bcl-xL", "anti-apoptotic",
            "tonic signaling", "tonic TCR",
            "tissue residency", "tissue homing",
            "PLZF", "T-bet", "NKT1", "NKT2", "NKT17",
            "NKT subset balance", "NKT maturation",
            "NKT cell fate", "NKT differentiation",
            "CD1d tetramer", "PBS-57",
        ],
        "context": [
            "homeostasis", "maintenance", "steady state",
            "survival", "apoptosis", "turnover",
            "self-renewal", "quiescence",
        ],
        "methods_of_interest": [
            "フローサイトメトリー", "マスサイトメトリー (CyTOF)",
            "シングルセル解析", "in vivoモデル", "機能アッセイ",
        ],
        "description_ja": "NKT細胞が生体内でどのように維持されるかの機構研究",
    },
    "NKTワクチン": {
        "primary": [
            "NKT vaccine", "NKT cell therapy",
            "NKT immunotherapy", "α-GalCer vaccine",
            "NKT adjuvant", "CAR-NKT",
            "NKT adoptive transfer", "NKT cell product",
            "NKT clinical trial", "NKT anti-tumor",
            "DC NKT vaccine",
        ],
        "secondary": [
            "dendritic cell NKT", "α-GalCer", "alpha-GalCer",
            "KRN7000", "NKT expansion",
            "NKT cell activation", "NKT cell therapy",
            "tumor rejection NKT", "cancer NKT",
            "NKT cell manufacturing",
            "GMP NKT", "clinical grade NKT",
            "NKT cell number recovery",
            "NKT immune response",
        ],
        "context": [
            "vaccine", "immunotherapy", "cell therapy",
            "clinical", "therapeutic", "adjuvant",
            "anti-tumor", "cancer treatment",
        ],
        "methods_of_interest": [
            "細胞培養・拡大培養", "臨床試験・トランスレーショナル",
            "DC負荷・ワクチン調製", "遺伝子操作・CRISPR", "機能アッセイ",
        ],
        "description_ja": "NKT細胞を利用したワクチン・細胞治療の開発研究",
    },
    "整形外科": {
        "primary": [
            "orthopedic", "orthopaedic",
            "fracture", "arthroplasty",
            "spinal", "spine surgery",
            "joint replacement", "bone graft",
            "orthopedic surgery", "musculoskeletal surgery",
            "rotator cuff", "ACL", "meniscus",
        ],
        "secondary": [
            "fracture healing", "bone repair",
            "osteoarthritis", "rheumatoid arthritis",
            "synovial inflammation", "joint inflammation",
            "surgical site", "implant",
            "biomaterial", "scaffold",
            "rehabilitation", "postoperative",
            "perioperative immune", "surgical stress",
            "wound healing",
        ],
        "context": [
            "surgery", "surgical", "joint", "bone injury",
            "musculoskeletal", "ligament", "tendon",
            "cartilage repair",
        ],
        "methods_of_interest": [
            "骨解析", "イメージング", "in vivoモデル",
            "臨床試験・トランスレーショナル",
        ],
        "description_ja": "整形外科疾患・手術における免疫応答と骨・関節の研究",
    },
    "骨代謝研究": {
        "primary": [
            "bone metabolism", "bone remodeling",
            "osteoclast", "osteoblast", "osteocyte",
            "RANKL", "OPG", "osteoprotegerin",
            "osteoimmunology",
            "bone resorption", "bone formation",
            "bone mineral density",
        ],
        "secondary": [
            "osteoporosis", "bone loss",
            "osteoclastogenesis", "osteoblastogenesis",
            "RANK", "M-CSF", "CSF1",
            "Wnt signaling", "BMP",
            "sclerostin", "cathepsin K",
            "TRAP", "alkaline phosphatase",
            "calcium", "phosphate",
            "vitamin D", "PTH", "parathyroid",
            "bone marrow niche", "hematopoietic niche",
            "mesenchymal stem cell", "MSC",
        ],
        "context": [
            "bone", "skeletal", "mineralization",
            "calcium homeostasis", "bone turnover",
            "bone microenvironment",
        ],
        "methods_of_interest": [
            "骨解析", "イメージング", "in vivoモデル",
            "シングルセル解析", "空間トランスクリプトーム",
        ],
        "description_ja": "骨のリモデリング機構と骨免疫学の基礎研究",
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
    research_area_scores: dict[str, float] = field(default_factory=dict)
    matched_areas: list[str] = field(default_factory=list)
    recommendation_reason: str = ""

    @property
    def primary_topic(self) -> str:
        if not self.topic_scores:
            return "iNKT development"
        return max(self.topic_scores, key=self.topic_scores.get)

    @property
    def primary_area(self) -> str:
        if not self.research_area_scores:
            return ""
        best = max(self.research_area_scores, key=self.research_area_scores.get)
        if self.research_area_scores[best] >= 0.10:
            return best
        return ""


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
    SCORE_THRESHOLD = 0.15

    # Weights for composite score
    WEIGHT_TOPIC = 0.40
    WEIGHT_AREA = 0.45
    WEIGHT_METHOD = 0.15

    def score_paper(self, paper: Paper) -> ScoredArticle:
        result = ScoredArticle(paper=paper)
        full_text = _build_searchable_text(paper)

        # 1. Topic scoring (existing)
        for topic_name, profile in TOPIC_PROFILES.items():
            score = self._score_topic(paper, full_text, profile)
            result.topic_scores[topic_name] = score
            if score >= self.SCORE_THRESHOLD:
                result.matched_topics.append(topic_name)

        # 2. Method detection
        result.matched_methods = self._detect_methods(full_text)

        # 3. Research area scoring
        for area_name, area_profile in LAB_RESEARCH_AREAS.items():
            score = self._score_research_area(paper, full_text, area_profile, result.matched_methods)
            result.research_area_scores[area_name] = score
            if score >= 0.10:
                result.matched_areas.append(area_name)

        # 4. Composite score
        topic_max = max(result.topic_scores.values()) if result.topic_scores else 0.0
        area_max = max(result.research_area_scores.values()) if result.research_area_scores else 0.0
        method_bonus = min(len(result.matched_methods) * 0.15, 0.5)

        result.total_score = min(
            self.WEIGHT_TOPIC * topic_max
            + self.WEIGHT_AREA * area_max
            + self.WEIGHT_METHOD * method_bonus,
            1.0,
        )

        # 5. Generate recommendation
        result.recommendation_reason = self._generate_recommendation(result)
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
        detected = []
        for method_name, profile in METHOD_PROFILES.items():
            for kw in profile["keywords"]:
                if _text_contains(full_text, kw):
                    detected.append(method_name)
                    break
        return detected

    def _score_research_area(
        self,
        paper: Paper,
        full_text: str,
        area_profile: dict,
        matched_methods: list[str],
    ) -> float:
        score = 0.0

        for term in area_profile.get("primary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.25 * mult

        for term in area_profile.get("secondary", []):
            if _text_contains(full_text, term):
                mult = self.TITLE_MULTIPLIER if _text_contains(paper.title, term) else 1.0
                score += 0.10 * mult

        for term in area_profile.get("context", []):
            if _text_contains(full_text, term):
                score += 0.03

        # Bonus: paper uses methods that are of interest to this area
        methods_of_interest = area_profile.get("methods_of_interest", [])
        overlap = set(matched_methods) & set(methods_of_interest)
        if overlap:
            score += len(overlap) * 0.05

        return min(score, 1.0)

    def _generate_recommendation(self, result: ScoredArticle) -> str:
        parts = []

        # Research area connection
        if result.matched_areas:
            area_details = []
            for area in result.matched_areas:
                desc = LAB_RESEARCH_AREAS[area]["description_ja"]
                area_score = result.research_area_scores[area]
                if area_score >= 0.4:
                    area_details.append(f"【{area}】に強く関連（{desc}）")
                elif area_score >= 0.2:
                    area_details.append(f"【{area}】に関連（{desc}）")
                else:
                    area_details.append(f"【{area}】に部分的に関連")
            parts.append("研究領域: " + "、".join(area_details))

        # Method connections
        if result.matched_methods:
            method_details = []
            for m in result.matched_methods:
                desc = METHOD_PROFILES[m]["description"]
                method_details.append(f"{m}（{desc}）")
            parts.append("手法: " + "、".join(method_details))

            # Cross-reference: methods that match area interests
            if result.matched_areas:
                for area in result.matched_areas:
                    moi = LAB_RESEARCH_AREAS[area].get("methods_of_interest", [])
                    overlap = set(result.matched_methods) & set(moi)
                    if overlap:
                        parts.append(
                            f"→ {area}研究に活かせる手法: {', '.join(overlap)}"
                        )

        # Topic info
        if result.matched_topics:
            parts.append(f"トピック: {', '.join(result.matched_topics)}")

        # Actionable suggestion based on score and matches
        if result.total_score >= 0.6:
            parts.append("★ 優先的に読むべき論文です")
        elif result.total_score >= 0.3:
            parts.append("☆ チェック推奨")

        if not parts:
            return "NKT細胞関連（一般）"

        return "\n".join(parts)

    def score_and_rank(self, papers: list[Paper]) -> list[ScoredArticle]:
        scored = [self.score_paper(p) for p in papers]
        scored.sort(key=lambda x: x.total_score, reverse=True)
        if scored:
            logger.info(f"Scored {len(scored)} papers. Top score: {scored[0].total_score:.2f}")
        return scored
