"""Notion Markdown content builder for 週刊NKT.

Generates properties and page content in Notion-flavored Markdown format,
ready for posting via Notion MCP tools (notion-create-pages).

Output matches the schema of the 週刊NKT（メルマガ）database:
  data_source_id: 5e5eca70-b1c4-4039-92fe-a92fcf8d21a0
"""

import json
from datetime import datetime, timedelta

from src.scorer.relevance import (
    ScoredArticle,
    LAB_RESEARCH_AREAS,
    METHOD_PROFILES,
)


DATA_SOURCE_ID = "5e5eca70-b1c4-4039-92fe-a92fcf8d21a0"

# Research area display order
AREA_ORDER = ["NKT恒常性維持", "NKTワクチン", "整形外科", "骨代謝研究"]


def _week_monday() -> str:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _issue_label() -> str:
    now = datetime.now()
    week_num = now.isocalendar()[1]
    return f"Vol.{week_num} — {now.year}-W{week_num:02d}"


def _date_range(days: int = 7) -> str:
    end = datetime.now()
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"


def _area_stars(score: float) -> str:
    if score >= 0.4:
        return "★★★"
    if score >= 0.2:
        return "★★"
    if score >= 0.10:
        return "★"
    return "—"


def _escape_md(text: str) -> str:
    """Escape pipe characters for Notion Markdown."""
    return text.replace("|", "\\|")


# ── Properties builder ──────────────────────────────────────────────

def build_properties(
    scored_papers: list[ScoredArticle],
    days: int = 7,
    duplicates_removed: int = 0,
) -> dict:
    """Build Notion database properties dict for MCP create-pages."""
    all_topics = sorted({t for s in scored_papers for t in s.matched_topics})

    intro = _build_intro_text(scored_papers, days, duplicates_removed)
    highlights = _build_highlights_text(scored_papers)
    body = _build_body_text(scored_papers)
    papers_list = _build_papers_list_text(scored_papers)

    props = {
        "Issue": _issue_label(),
        "date:Week:start": _week_monday(),
        "date:Week:is_datetime": 0,
        "Status": "Draft",
        "Source": "Claude Code",
        "Topics": json.dumps(all_topics),
        "Intro (JP)": intro,
        "Highlights": highlights,
        "Body (JP)": body,
        "Papers (list)": papers_list,
    }
    return props


def _build_intro_text(
    scored_papers: list[ScoredArticle],
    days: int,
    duplicates_removed: int,
) -> str:
    if not scored_papers:
        return "今週はNKT関連の新規論文はありませんでした。次週に期待しましょう。"

    top_score = scored_papers[0].total_score
    n = len(scored_papers)

    parts = []

    if top_score >= 0.6:
        parts.append("今週は注目すべき論文あり —")
    elif top_score >= 0.3:
        parts.append("今週は関連論文あり。")
    else:
        parts.append("今週もNKT関連の論文をお届けします。")

    # Top paper callout
    if top_score >= 0.15:
        top = scored_papers[0]
        if top.matched_areas:
            area_str = "・".join(top.matched_areas)
            parts.append(
                f"特に #1 の{top.paper.first_author} et al. "
                f"({top.paper.journal}) は{area_str}研究に関連する知見です。"
            )

    # Method highlights
    all_methods = set()
    for s in scored_papers:
        all_methods.update(s.matched_methods)
    if all_methods:
        parts.append(
            f"method面では{', '.join(sorted(all_methods)[:3])}等の手法が報告されています。"
        )

    date_range = _date_range(days)
    parts.append(f"検索期間: {date_range} \\| 新規論文: {n}件")
    if duplicates_removed > 0:
        parts[-1] += f"（既出{duplicates_removed}件を除外）"

    return " ".join(parts)


def _build_highlights_text(scored_papers: list[ScoredArticle]) -> str:
    lines = []
    for s in scored_papers[:10]:
        icon = "🎯" if s.total_score >= 0.6 else "⭐" if s.total_score >= 0.3 else "📊"
        topic_str = " / ".join(s.matched_topics[:2]) if s.matched_topics else "General"
        lines.append(
            f"• {icon} \\[{_escape_md(topic_str)}\\] "
            f"{_escape_md(s.paper.title[:100])} "
            f"({s.paper.first_author} et al., {_escape_md(s.paper.journal)})"
        )
    return "\n".join(lines)


def _build_body_text(scored_papers: list[ScoredArticle]) -> str:
    sections = []
    for i, s in enumerate(scored_papers, 1):
        p = s.paper
        topic_tags = ", ".join(s.matched_topics) if s.matched_topics else "General"
        lines = [
            f"── #{i} ──",
            _escape_md(p.title),
            f"{p.first_author} et al. \\| {_escape_md(p.journal)} \\| {p.pub_date}",
            f"Topics: {_escape_md(topic_tags)} \\| Score: {s.total_score:.2f}",
        ]

        # Research area stars
        area_parts = []
        for area in AREA_ORDER:
            score = s.research_area_scores.get(area, 0)
            if score >= 0.10:
                area_parts.append(f"{area}（{_area_stars(score)}）")
        if area_parts:
            lines.append(f"研究軸: {' / '.join(area_parts)}")

        # Methods
        if s.matched_methods:
            lines.append(f"手法: {', '.join(s.matched_methods)}")

        # Recommendation
        if s.recommendation_reason:
            lines.append(f"応用可能性: {s.recommendation_reason}")

        lines.append(
            f"PMID: {p.pmid} \\| "
            f"[{p.url}]({p.url})"
        )
        if p.doi:
            lines.append(f"DOI: {p.doi}")

        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _build_papers_list_text(scored_papers: list[ScoredArticle]) -> str:
    lines = []
    for s in scored_papers:
        p = s.paper
        parts = [f"• {_escape_md(p.title)}"]
        parts.append(f"  PMID: {p.pmid}")
        if p.doi:
            parts.append(f"  DOI: {p.doi}")
        parts.append(f"  URL: [{p.url}]({p.url})")
        lines.append("\n".join(parts))
    return "\n".join(lines)


# ── Page content (Notion Markdown) ──────────────────────────────────

def build_page_content(
    scored_papers: list[ScoredArticle],
    days: int = 7,
    duplicates_removed: int = 0,
) -> str:
    """Build full page body in Notion-flavored Markdown."""
    if not scored_papers:
        return (
            "> 💡 今週はNKT関連の新規論文はありませんでした。次週に期待しましょう。\n"
        )

    blocks = []

    # ── Callout: weekly recommendation
    top = scored_papers[0]
    if top.total_score >= 0.3 and top.matched_areas:
        area_str = "・".join(top.matched_areas)
        blocks.append(
            f"> 💡 **今週のおすすめ**: #1 {top.paper.first_author} et al. "
            f"({top.paper.journal}) — {area_str}研究に関連。"
            f"Score: {top.total_score:.2f}"
        )
    else:
        blocks.append(
            f"> 💡 今週のNKT関連論文は{len(scored_papers)}件です。"
        )

    blocks.append("---")

    # ── Research area summary
    date_range = _date_range(days)
    blocks.append(f"## 📌 研究領域別サマリ（{date_range}）")
    blocks.append(f"- 新規論文数: **{len(scored_papers)}件**")

    if duplicates_removed > 0:
        blocks.append(f"- 既出除外: {duplicates_removed}件")

    blocks.append("- 研究軸別:")
    for area in AREA_ORDER:
        papers_in_area = [
            s for s in scored_papers if area in s.matched_areas
        ]
        if papers_in_area:
            paper_refs = ", ".join(
                f"#{scored_papers.index(s)+1} {_area_stars(s.research_area_scores.get(area,0))}"
                for s in papers_in_area[:5]
            )
            blocks.append(f"\t- **{area}**: {paper_refs}")
        else:
            blocks.append(f"\t- **{area}**: 該当なし")

    # Topic counts
    topic_counts: dict[str, int] = {}
    for s in scored_papers:
        for t in s.matched_topics:
            topic_counts[t] = topic_counts.get(t, 0) + 1
    if topic_counts:
        blocks.append("- トピック:")
        for t, c in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True):
            blocks.append(f"\t- {t}: {c}件")

    blocks.append("---")

    # ── Method summary
    method_counts: dict[str, int] = {}
    for s in scored_papers:
        for m in s.matched_methods:
            method_counts[m] = method_counts.get(m, 0) + 1

    if method_counts:
        blocks.append("## 🔬 検出された手法")
        for m, c in sorted(method_counts.items(), key=lambda x: x[1], reverse=True):
            desc = METHOD_PROFILES[m]["description"]
            blocks.append(f"- **{m}** ({c}件): {desc}")
        blocks.append("---")

    # ── Each paper
    for rank, s in enumerate(scored_papers, 1):
        p = s.paper
        blocks.append(f"## #{rank} {_escape_md(p.title)}")
        blocks.append(
            f"{p.first_author} et al. \\| **{_escape_md(p.journal)}** \\| {p.pub_date}"
        )

        # Score and topics
        topic_str = ", ".join(s.matched_topics) if s.matched_topics else "General"
        blocks.append(
            f"**Score: {s.total_score:.2f}** \\| Topics: {_escape_md(topic_str)}"
        )

        # Research area connections
        blocks.append("**研究軸との関連**")
        for area in AREA_ORDER:
            score = s.research_area_scores.get(area, 0)
            stars = _area_stars(score)
            if score >= 0.10:
                desc = LAB_RESEARCH_AREAS[area]["description_ja"]
                blocks.append(f"- {'🎯 ' if score >= 0.4 else ''}**{area}** ({stars}): {desc}")
            else:
                blocks.append(f"- **{area}** ({stars})")

        # Methods
        if s.matched_methods:
            blocks.append("**検出された手法**")
            for m in s.matched_methods:
                desc = METHOD_PROFILES[m]["description"]
                blocks.append(f"- {m}: {desc}")

        # Recommendation
        if s.recommendation_reason:
            blocks.append("**コンセプト的応用**")
            blocks.append(s.recommendation_reason)

        # Links
        blocks.append(
            f"[PubMed: {p.pmid}]({p.url})"
        )
        if p.doi:
            blocks.append(
                f" \\| [DOI: {p.doi}](https://doi.org/{p.doi})"
            )

        # Abstract toggle
        if p.abstract:
            blocks.append("<details>")
            blocks.append("<summary>Abstract</summary>")
            blocks.append(f"\t{_escape_md(p.abstract[:2000])}")
            blocks.append("</details>")

        blocks.append("---")

    # ── Action summary
    blocks.append("## 📌 まとめ — 今週のアクション")

    action_num = 1
    for rank, s in enumerate(scored_papers, 1):
        if s.total_score >= 0.3:
            blocks.append(
                f"{action_num}. **#{rank} は要精読** — "
                f"{s.paper.first_author} et al. "
                f"({', '.join(s.matched_areas) if s.matched_areas else 'NKT関連'})"
            )
            action_num += 1
        elif s.total_score >= 0.15:
            blocks.append(
                f"{action_num}. #{rank} はスキャン推奨 — "
                f"{s.paper.first_author} et al."
            )
            action_num += 1

    low_relevance = [s for s in scored_papers if s.total_score < 0.15]
    if low_relevance:
        refs = ", ".join(
            f"#{scored_papers.index(s)+1}" for s in low_relevance
        )
        blocks.append(f"{action_num}. {refs} はスキップ可")

    blocks.append(
        f"\n*検索: PubMed \\| 出典: PubMed E-utilities*\n"
        f"*自動生成: Claude Code（PubMed + Notion MCP統合）*"
    )

    return "\n".join(blocks)


# ── Full export ─────────────────────────────────────────────────────

def build_newsletter(
    scored_papers: list[ScoredArticle],
    days: int = 7,
    duplicates_removed: int = 0,
) -> dict:
    """Build complete newsletter data for Notion MCP posting.

    Returns:
        dict with keys:
          - data_source_id: str
          - properties: dict (for Notion DB properties)
          - content: str (Notion Markdown for page body)
    """
    return {
        "data_source_id": DATA_SOURCE_ID,
        "properties": build_properties(scored_papers, days, duplicates_removed),
        "content": build_page_content(scored_papers, days, duplicates_removed),
    }
