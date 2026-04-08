"""Notion API client for 週刊NKT（メルマガ）database.

Creates one page per weekly issue (newsletter format):
  - Issue (title): e.g. "Vol.15 — 2026-W15"
  - Week (date): Monday of the week
  - Status (status): Draft
  - Source (select): Claude Code
  - Topics (multi_select): aggregated from all papers
  - Intro (JP) (text): short overall summary
  - Highlights (text): bullet-point headlines
  - Body (JP) (text): per-paper short summaries
  - Papers (list) (text): title/PMID/DOI/URL list
"""

import logging
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.scorer.relevance import ScoredArticle

logger = logging.getLogger(__name__)

DATABASE_ID = "a1f5b30f-0402-4ddf-a872-c42622d9c27c"


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


class NotionClient:
    """Client for posting weekly newsletter issues to Notion."""

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.notion_database_id or DATABASE_ID

    def _get_week_monday(self) -> str:
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def _get_issue_label(self) -> str:
        now = datetime.now()
        week_num = now.isocalendar()[1]
        return f"Vol.{week_num} — {now.year}-W{week_num:02d}"

    def _build_intro(self, scored_papers: list[ScoredArticle]) -> str:
        """Build a short intro summarizing this week's papers."""
        total = len(scored_papers)
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.matched_topics)

        date_range = self._date_range_str()
        lines = [
            f"今週のNKT細胞関連論文は{total}件でした（{date_range}）。",
        ]
        if all_topics:
            lines.append(f"カバーされたトピック: {', '.join(sorted(all_topics))}")

        top3 = scored_papers[:3]
        if top3:
            lines.append("")
            lines.append("注目論文:")
            for i, s in enumerate(top3, 1):
                lines.append(f"  {i}. {s.paper.title[:80]}")

        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[ScoredArticle]) -> str:
        """Build bullet-point headlines."""
        lines = []
        for i, s in enumerate(scored_papers[:10], 1):
            topic_str = f"[{s.primary_topic}]" if s.matched_topics else ""
            first_author = s.paper.first_author
            lines.append(
                f"• {topic_str} {s.paper.title[:100]} "
                f"({first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _build_body(self, scored_papers: list[ScoredArticle]) -> str:
        """Build the body with per-paper summaries."""
        sections = []
        for i, s in enumerate(scored_papers, 1):
            p = s.paper
            topic_tags = ", ".join(s.matched_topics) if s.matched_topics else "General"
            first_author = p.first_author

            section = [
                f"── #{i} ──",
                f"{p.title}",
                f"{first_author} et al. | {p.journal} | {p.pub_date}",
                f"Topics: {topic_tags} | Score: {s.total_score:.2f}",
                f"PMID: {p.pmid} | {p.url}",
            ]
            if p.doi:
                section.append(f"DOI: {p.doi}")

            # Add abstract excerpt (first 300 chars)
            if p.abstract:
                excerpt = p.abstract[:300]
                if len(p.abstract) > 300:
                    excerpt += "..."
                section.append(f"\n{excerpt}")

            sections.append("\n".join(section))

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[ScoredArticle]) -> str:
        """Build a simple list of papers with key identifiers."""
        lines = []
        for s in scored_papers:
            p = s.paper
            parts = [f"• {p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _date_range_str(self, days: int = 7) -> str:
        end = datetime.now()
        start = end - timedelta(days=days)
        return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"

    def _collect_all_topics(self, scored_papers: list[ScoredArticle]) -> list[str]:
        """Collect all unique topics from all papers."""
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.matched_topics)
        return sorted(all_topics)

    def post_weekly_issue(self, scored_papers: list[ScoredArticle], days: int = 7) -> str:
        """Post a weekly newsletter issue to the Notion database.

        Returns the page URL if successful.
        """
        if not self.database_id:
            raise ValueError("NOTION_DATABASE_ID is required.")

        intro = self._build_intro(scored_papers)
        highlights = self._build_highlights(scored_papers)
        body = self._build_body(scored_papers)
        papers_list = self._build_papers_list(scored_papers)
        all_topics = self._collect_all_topics(scored_papers)

        properties = {
            "Issue": {
                "title": _rich_text(self._get_issue_label()),
            },
            "Week": {
                "date": {"start": self._get_week_monday()},
            },
            "Status": {
                "status": {"name": "Draft"},
            },
            "Source": {
                "select": {"name": "Claude Code"},
            },
            "Topics": {
                "multi_select": [{"name": t} for t in all_topics],
            },
            "Intro (JP)": {
                "rich_text": _rich_text(intro),
            },
            "Highlights": {
                "rich_text": _rich_text(highlights),
            },
            "Body (JP)": {
                "rich_text": _rich_text(body),
            },
            "Papers (list)": {
                "rich_text": _rich_text(papers_list),
            },
        }

        # Build page body blocks for richer formatting
        children = self._build_page_blocks(scored_papers)

        try:
            time.sleep(self.RATE_LIMIT_DELAY)
            # Create page with first 100 blocks
            first_batch = children[:100]
            remaining = children[100:]

            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=first_batch,
            )
            page_id = page["id"]
            page_url = page.get("url", "")

            # Append remaining blocks
            for i in range(0, len(remaining), 100):
                time.sleep(self.RATE_LIMIT_DELAY)
                batch = remaining[i:i + 100]
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=batch,
                )

            logger.info(f"Posted weekly issue to Notion: {page_url}")
            return page_url

        except APIResponseError as e:
            if e.status == 429:
                logger.warning("Rate limited. Retrying in 2s...")
                time.sleep(2.0)
                try:
                    page = self.client.pages.create(
                        parent={"database_id": self.database_id},
                        properties=properties,
                        children=children[:100],
                    )
                    return page.get("url", "")
                except APIResponseError:
                    logger.error("Retry failed")
                    raise
            else:
                logger.error(f"Notion API error: {e}")
                raise

    def _build_page_blocks(self, scored_papers: list[ScoredArticle]) -> list[dict]:
        """Build rich page body blocks."""
        blocks = []

        # Intro heading
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": _rich_text("📊 今週のサマリ")},
        })

        # Stats callout
        topic_counts: dict[str, int] = {}
        for s in scored_papers:
            for t in s.matched_topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1

        stats_lines = [f"総論文数: {len(scored_papers)}"]
        for t, c in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True):
            stats_lines.append(f"  • {t}: {c}件")

        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text("\n".join(stats_lines)),
                "icon": {"type": "emoji", "emoji": "📈"},
            },
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Each paper
        for rank, s in enumerate(scored_papers, 1):
            p = s.paper

            # Title
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(f"#{rank} {p.title}")},
            })

            # Metadata
            meta = (
                f"{p.first_author} et al. | {p.journal} | {p.pub_date}\n"
                f"Score: {s.total_score:.2f} | "
                f"Topics: {', '.join(s.matched_topics) if s.matched_topics else 'General'}"
            )
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(meta)},
            })

            # PubMed link
            blocks.append({
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": p.url},
            })

            # Abstract toggle
            if p.abstract:
                blocks.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": _rich_text("Abstract"),
                        "children": [{
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": _rich_text(p.abstract[:2000])},
                        }],
                    },
                })

            blocks.append({"object": "block", "type": "divider", "divider": {}})

        return blocks

    def verify_connection(self) -> bool:
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            title_parts = db.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            logger.info(f"Connected to Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
