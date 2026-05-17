"""Maps papers to the lab's research interests via concept and method connections.

Generates Japanese-language explanations of HOW each paper relates to:
  - NKT恒常性維持 (NKT homeostasis)
  - NKTワクチン (NKT vaccine / immunotherapy)
  - 整形外科・骨代謝 (Orthopedics / bone metabolism)
  - 免疫制御・自己寛容 (Immune regulation / tolerance)
"""

import re
from dataclasses import dataclass, field

from src.pubmed.client import Paper


@dataclass
class ConceptConnection:
    theme: str
    explanation: str
    strength: float  # 0.0-1.0


@dataclass
class MethodApplication:
    technique: str
    explanation: str
    strength: float


@dataclass
class PaperAnalysis:
    paper: Paper
    concepts: list[ConceptConnection] = field(default_factory=list)
    methods: list[MethodApplication] = field(default_factory=list)
    japanese_summary: str = ""
    recommendation_text: str = ""

    @property
    def top_concept(self) -> str:
        if not self.concepts:
            return ""
        return max(self.concepts, key=lambda c: c.strength).explanation

    @property
    def top_method(self) -> str:
        if not self.methods:
            return ""
        return max(self.methods, key=lambda m: m.strength).explanation


# ── Lab Research Themes with detection patterns ──────────────────────────

CONCEPT_THEMES = {
    "NKT恒常性維持": {
        "patterns": [
            (r"(?i)homeostasis.*NKT|NKT.*homeostasis", 0.9),
            (r"(?i)NKT.*maintenance|maintenance.*NKT", 0.8),
            (r"(?i)NKT.*survival|survival.*NKT", 0.8),
            (r"(?i)NKT.*development|iNKT.*development", 0.7),
            (r"(?i)NKT.*proliferation|iNKT.*proliferation", 0.7),
            (r"(?i)tissue.?resident.*NKT|NKT.*tissue.?resident", 0.7),
            (r"(?i)NKT.*maturation|NKT.*differentiation", 0.6),
            (r"(?i)IL-7.*NKT|IL-15.*NKT|NKT.*IL-7|NKT.*IL-15", 0.7),
            (r"(?i)NKT.*subset|NKT1|NKT2|NKT17", 0.5),
            (r"(?i)PLZF|Zbtb16", 0.5),
            (r"(?i)CD1d.*restrict|α-GalCer|alpha-GalCer", 0.4),
            (r"(?i)stromal.*NKT|niche.*NKT|NKT.*niche", 0.7),
            (r"(?i)BMP.*NKT|NKT.*BMP|Wnt.*NKT", 0.7),
        ],
        "explanation_templates": [
            ("homeostasis|maintenance|survival", "NKT細胞の末梢での維持機構 — 当ラボのコアテーマに直結"),
            ("development|maturation|differentiation", "NKT細胞の分化・成熟過程の理解に貢献"),
            ("tissue.?resident|niche|stromal", "NKT細胞のニッチ・微小環境の解明に関連"),
            ("proliferation|turnover", "NKT細胞の増殖制御機構の研究に参考"),
            ("IL-7|IL-15|cytokine", "NKT細胞の恒常性維持サイトカインシグナルに関連"),
            ("subset|NKT1|NKT2|NKT17", "NKTサブセットの機能分化の理解に貢献"),
        ],
    },
    "NKTワクチン・免疫療法": {
        "patterns": [
            (r"(?i)NKT.*vaccin|vaccin.*NKT|iNKT.*vaccin", 0.9),
            (r"(?i)CAR.?NKT|chimeric.*NKT", 0.9),
            (r"(?i)NKT.*immunotherapy|immunotherapy.*NKT", 0.85),
            (r"(?i)α-GalCer.*adjuvant|adjuvant.*α-GalCer|GalCer.*adjuvant", 0.8),
            (r"(?i)NKT.*anti.?tumor|anti.?tumor.*NKT", 0.8),
            (r"(?i)NKT.*adoptive|adoptive.*NKT", 0.8),
            (r"(?i)NKT.*cell.?therapy|cell.?therapy.*NKT", 0.85),
            (r"(?i)NKT.*expansion|expansion.*NKT", 0.6),
            (r"(?i)NKT.*activation.*DC|DC.*NKT.*activation", 0.7),
            (r"(?i)NKT.*clinical|clinical.*NKT", 0.6),
            (r"(?i)tumor.*NKT|NKT.*tumor|cancer.*NKT", 0.5),
            (r"(?i)checkpoint.*NKT|NKT.*PD-1|NKT.*PD-L1", 0.6),
            (r"(?i)immune.*response.*enhanced|enhanced.*immune", 0.3),
        ],
        "explanation_templates": [
            ("vaccin|adjuvant", "NKTワクチン開発 — 臨床応用の基盤研究"),
            ("CAR.?NKT|chimeric|cell.?therapy|adoptive", "CAR-NKT / 細胞治療の最新知見"),
            ("anti.?tumor|tumor|cancer", "NKTの抗腫瘍活性 — ワクチン戦略への示唆"),
            ("expansion|activation", "NKT細胞の活性化・増殖法 — 治療用プロトコル開発"),
            ("DC|dendritic", "DC-NKT相互作用 — ワクチンデザインの基盤"),
            ("clinical|trial|patient", "臨床応用・トランスレーショナル研究の参考"),
        ],
    },
    "整形外科・骨代謝": {
        "patterns": [
            (r"(?i)osteoimmunolog", 0.9),
            (r"(?i)bone.*metasta|metasta.*bone", 0.8),
            (r"(?i)osteoclast|osteoblast|osteocyte", 0.8),
            (r"(?i)RANKL|OPG|osteoprotegerin", 0.8),
            (r"(?i)bone.*remodel|bone.*resorption|bone.*formation", 0.7),
            (r"(?i)bone.*metabolism|bone.*mineral", 0.7),
            (r"(?i)osteoporo|osteoarthri|rheumatoid.*arthri", 0.6),
            (r"(?i)fracture|bone.*heal|bone.*repair", 0.7),
            (r"(?i)orthop|arthroplast|spine|spinal", 0.6),
            (r"(?i)synovial|joint.*inflam|cartilage", 0.5),
            (r"(?i)musculoskeletal", 0.5),
            (r"(?i)bone.*immune|immune.*bone", 0.7),
            (r"(?i)NKT.*bone|bone.*NKT", 0.9),
            (r"(?i)bone.*marrow.*NKT|NKT.*bone.*marrow", 0.7),
        ],
        "explanation_templates": [
            ("osteoimmunolog|bone.*immune|immune.*bone", "骨免疫学 — 免疫系と骨代謝のクロストーク"),
            ("metasta.*bone|bone.*metasta", "骨転移の免疫微小環境 — 治療標的の探索"),
            ("osteoclast|RANKL|resorption", "骨吸収・破骨細胞制御 — NKTとの接点に注目"),
            ("osteoblast|bone.*form|bone.*heal|repair", "骨形成・骨修復 — 再生医療への接点"),
            ("fracture|orthop|arthroplast|spine", "整形外科的疾患 — 臨床研究との接点"),
            ("osteoporo|osteoarthri|rheumatoid", "骨・関節疾患の免疫学的理解"),
            ("bone.*marrow", "骨髄微小環境 — NKT細胞のニッチとして重要"),
        ],
    },
    "免疫制御・自己寛容": {
        "patterns": [
            (r"(?i)NKT.*regulat|regulat.*NKT", 0.7),
            (r"(?i)NKT.*toleran|toleran.*NKT", 0.8),
            (r"(?i)NKT.*suppress|suppress.*NKT", 0.7),
            (r"(?i)B.*cell.*toleran|toleran.*B.*cell", 0.8),
            (r"(?i)NKT.*B.*cell|B.*cell.*NKT", 0.7),
            (r"(?i)autoimmun.*NKT|NKT.*autoimmun", 0.6),
            (r"(?i)NKT.*IL-4|IL-4.*NKT|NKT.*IFN|IFN.*NKT", 0.5),
            (r"(?i)immune.*homeostasis|homeostasis.*immune", 0.5),
            (r"(?i)self.?reactive|autoreactive", 0.5),
            (r"(?i)immune.*regulat|regulatory.*immune", 0.4),
        ],
        "explanation_templates": [
            ("toleran|self.?reactive|autoreactive", "免疫寛容 — NKTによるB細胞寛容誘導との接点"),
            ("regulat|suppress", "NKTの免疫制御機能 — 恒常性維持の広義の文脈"),
            ("B.*cell.*NKT|NKT.*B.*cell", "NKT-B細胞相互作用 — 当ラボの研究テーマに直結"),
            ("autoimmun", "自己免疫疾患とNKT — 制御メカニズムの解明"),
            ("IL-4|IFN|cytokine", "NKTサイトカイン応答 — 免疫制御の分子基盤"),
        ],
    },
}

METHOD_PATTERNS = {
    "α-GalCer / 脂質抗原": {
        "patterns": [
            (r"(?i)α-GalCer|alpha-GalCer|αGalCer", 0.9),
            (r"(?i)lipid.*antigen|glycolipid.*antigen", 0.7),
            (r"(?i)CD1d.*load|CD1d.*present", 0.6),
            (r"(?i)lipid.*analog|glycolipid.*analog", 0.7),
        ],
        "explanation": "NKTワクチン・NKT活性化プロトコルに直結",
    },
    "CAR-NKT / 細胞工学": {
        "patterns": [
            (r"(?i)CAR.?NKT|CAR.*NKT|NKT.*CAR", 0.9),
            (r"(?i)chimeric.*antigen.*NKT", 0.9),
            (r"(?i)NKT.*engineer|engineer.*NKT", 0.8),
            (r"(?i)adoptive.*NKT|NKT.*adoptive", 0.7),
            (r"(?i)gene.*modif.*NKT|NKT.*gene.*modif", 0.7),
        ],
        "explanation": "NKT細胞治療・ワクチンへの応用技術",
    },
    "フローサイトメトリー / CyTOF": {
        "patterns": [
            (r"(?i)flow.*cytometry|FACS", 0.5),
            (r"(?i)CyTOF|mass.*cytometry", 0.7),
            (r"(?i)spectral.*flow", 0.7),
            (r"(?i)NKT.*phenotyp|phenotyp.*NKT", 0.5),
        ],
        "explanation": "NKT細胞の表現型解析・サブセット同定に応用可能",
    },
    "scRNA-seq / 空間トランスクリプトーム": {
        "patterns": [
            (r"(?i)scRNA.?seq|single.?cell.*RNA", 0.8),
            (r"(?i)spatial.*transcript", 0.8),
            (r"(?i)CITE.?seq|multiome", 0.7),
            (r"(?i)ATAC.?seq.*NKT|NKT.*ATAC", 0.7),
        ],
        "explanation": "NKT細胞の分子プロファイリング・ヘテロジェニティ解析",
    },
    "骨代謝評価法": {
        "patterns": [
            (r"(?i)micro.?CT.*bone|bone.*micro.?CT", 0.7),
            (r"(?i)bone.*densitom|DXA|DEXA", 0.6),
            (r"(?i)bone.*histomorpho", 0.8),
            (r"(?i)TRAP.*stain|osteoclast.*assay", 0.7),
            (r"(?i)Hounsfield|HU.*value.*bone", 0.5),
            (r"(?i)bone.*mineral.*density|BMD", 0.6),
        ],
        "explanation": "骨代謝研究の評価系 — 当ラボの整形外科研究に応用",
    },
    "免疫モニタリング": {
        "patterns": [
            (r"(?i)immune.*monitor|monitor.*immune", 0.6),
            (r"(?i)immune.*function.*change|change.*immune.*function", 0.5),
            (r"(?i)NK.*cell.*proportion|NKT.*cell.*proportion", 0.6),
            (r"(?i)CD4.*CD8.*ratio", 0.4),
            (r"(?i)immune.*panel|lymphocyte.*subset", 0.5),
        ],
        "explanation": "免疫モニタリング手法 — NKTの恒常性評価に参考",
    },
    "放射線・局所治療 + 免疫": {
        "patterns": [
            (r"(?i)radiot.*immun|immun.*radiot", 0.6),
            (r"(?i)brachytherap.*immun|immun.*brachytherap", 0.7),
            (r"(?i)seed.*implant.*immun|immun.*seed", 0.6),
            (r"(?i)abscopal|radiation.*immune", 0.6),
            (r"(?i)local.*therap.*immun|immun.*local", 0.5),
        ],
        "explanation": "局所治療と免疫応答の連動 — NKTワクチンとの併用の可能性",
    },
    "バイオインフォマティクス / pan-cancer解析": {
        "patterns": [
            (r"(?i)pan.?cancer|TCGA.*analy", 0.5),
            (r"(?i)bioinformat|computational.*immun", 0.4),
            (r"(?i)immune.*infiltrat.*analy|tumor.*microenviron.*analy", 0.5),
            (r"(?i)immune.*cell.*deconvolut|TIMER|CIBERSORT", 0.5),
        ],
        "explanation": "NKT細胞の組織内局在・細胞間相互作用の可視化に応用",
    },
}


class ConceptMethodMapper:
    """Analyzes papers for concept and method connections to lab research."""

    def analyze(self, paper: Paper) -> PaperAnalysis:
        text = self._build_text(paper)
        analysis = PaperAnalysis(paper=paper)

        # Find concept connections
        for theme_name, theme_config in CONCEPT_THEMES.items():
            connection = self._match_concept(text, paper.title, theme_name, theme_config)
            if connection:
                analysis.concepts.append(connection)

        # Find method applications
        for method_name, method_config in METHOD_PATTERNS.items():
            application = self._match_method(text, paper.title, method_name, method_config)
            if application:
                analysis.methods.append(application)

        analysis.concepts.sort(key=lambda c: c.strength, reverse=True)
        analysis.methods.sort(key=lambda m: m.strength, reverse=True)

        analysis.recommendation_text = self._build_recommendation(analysis)
        analysis.japanese_summary = self._build_summary(paper, analysis)

        return analysis

    def _build_text(self, paper: Paper) -> str:
        return " ".join([
            paper.title, paper.abstract,
            " ".join(paper.keywords), " ".join(paper.mesh_terms),
        ])

    def _match_concept(
        self, text: str, title: str, theme_name: str, config: dict
    ) -> ConceptConnection | None:
        max_strength = 0.0
        for pattern, base_strength in config["patterns"]:
            if re.search(pattern, text):
                mult = 1.3 if re.search(pattern, title) else 1.0
                strength = min(base_strength * mult, 1.0)
                max_strength = max(max_strength, strength)

        if max_strength < 0.3:
            return None

        explanation = self._select_explanation(text, config["explanation_templates"])
        if not explanation:
            explanation = f"{theme_name}に関連する報告"

        return ConceptConnection(
            theme=theme_name,
            explanation=explanation,
            strength=max_strength,
        )

    def _match_method(
        self, text: str, title: str, method_name: str, config: dict
    ) -> MethodApplication | None:
        max_strength = 0.0
        for pattern, base_strength in config["patterns"]:
            if re.search(pattern, text):
                mult = 1.3 if re.search(pattern, title) else 1.0
                strength = min(base_strength * mult, 1.0)
                max_strength = max(max_strength, strength)

        if max_strength < 0.4:
            return None

        return MethodApplication(
            technique=method_name,
            explanation=config["explanation"],
            strength=max_strength,
        )

    def _select_explanation(self, text: str, templates: list[tuple[str, str]]) -> str:
        for pattern, explanation in templates:
            if re.search(f"(?i){pattern}", text):
                return explanation
        return ""

    def _build_recommendation(self, analysis: PaperAnalysis) -> str:
        parts = []
        if analysis.concepts:
            top = analysis.concepts[0]
            parts.append(f"[コンセプト]{top.explanation}")
        if analysis.methods:
            top = analysis.methods[0]
            parts.append(f"[手法]{top.explanation}")
        if not parts:
            return "NKT細胞関連の報告"
        return " / ".join(parts)

    def _build_summary(self, paper: Paper, analysis: PaperAnalysis) -> str:
        if not paper.abstract:
            return ""

        abstract = paper.abstract
        sentences = re.split(r'(?<=[.!?])\s+', abstract)

        # Extract conclusion/results sentences
        key_sentences = []
        for s in sentences:
            lower = s.lower()
            if any(kw in lower for kw in [
                "conclude", "suggest", "demonstrate", "reveal",
                "indicate", "show that", "found that", "our results",
                "these findings", "this study", "we found",
            ]):
                key_sentences.append(s)

        if not key_sentences:
            key_sentences = sentences[-2:] if len(sentences) >= 2 else sentences

        summary = " ".join(key_sentences)
        if len(summary) > 500:
            summary = summary[:497] + "..."

        return summary
