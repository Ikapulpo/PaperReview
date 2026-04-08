"""Notion API client for posting weekly NKT paper summaries.

Assumes a Notion database '週刊NKT' with the following properties:
  - タイトル (Title): Week label e.g. "2026-W15 NKT論文サマリ"
  - 期間 (Rich Text): Date range
  - ステータス (Select): "新規" / "確認済"
  - 論文数 (Number): Total papers found

The paper details are written as page content (blocks).
"""

import logging
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.scorer.relevance import RelevanceScore

logger = logging.getLogger(__name__)


def _truncate(text: str, max_len: int = 2000) -> str:
    """Truncate text to Notion's block text limit."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _rich_text(content: str) -> list[dict]:
    """Create a Notion rich text array."""
    return [{"type": "text", "text": {"content": _truncate(content)}}]


def _rich_text_with_link(content: str, url: str) -> list[dict]:
    """Create a Notion rich text array with a link."""
    return [{"type": "text", "text": {"content": content, "link": {"url": url}}}]


class NotionClient:
    """Client for posting weekly NKT paper reviews to Notion."""

    def __init__(self):
        if not config.notion_api_key:
            raise ValueError(
                "NOTION_API_KEY is required. "
                "Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=config.notion_api_key)
        self.database_id = config.notion_database_id

    def _week_label(self) -> str:
        """Generate week label like '2026-W15 NKT論文サマリ'."""
        now = datetime.now()
        week_num = now.isocalendar()[1]
        return f"{now.year}-W{week_num:02d} NKT論文サマリ"

    def _date_range_str(self, days: int = 7) -> str:
        """Generate date range string."""
        end = datetime.now()
        start = end - timedelta(days=days)
        return f"{start.strftime('%Y/%m/%d')} - {end.strftime('%Y/%m/%d')}"

    def _build_paper_blocks(self, scored: RelevanceScore, rank: int) -> list[dict]:
        """Build Notion blocks for a single paper."""
        paper = scored.paper
        blocks = []

        # Heading: rank + title
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {
                "rich_text": _rich_text(f"#{rank} {paper.title}"),
            },
        })

        # Metadata line
        meta_parts = [
            f"著者: {paper.first_author} et al.",
            f"雑誌: {paper.journal}",
            f"日付: {paper.pub_date}",
        ]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": _rich_text(" | ".join(meta_parts)),
            },
        })

        # PubMed link
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": _rich_text_with_link(
                    f"PubMed: {paper.pmid}", paper.url
                ),
            },
        })

        # Relevance score and reason
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(
                    f"関連度スコア: {scored.total_score:.1f}\n"
                    f"{scored.recommendation_reason}"
                ),
                "icon": {"type": "emoji", "emoji": "🔬"},
            },
        })

        # Abstract (toggle block for space saving)
        if paper.abstract:
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text("Abstract"),
                    "children": [
                        {
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {
                                "rich_text": _rich_text(paper.abstract),
                            },
                        }
                    ],
                },
            })

        # Divider
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {},
        })

        return blocks

    def _build_summary_blocks(self, scored_papers: list[RelevanceScore]) -> list[dict]:
        """Build a summary section at the top of the page."""
        blocks = []

        # Header
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": _rich_text("📊 今週のサマリ"),
            },
        })

        # Stats by research interest
        interest_counts: dict[str, int] = {}
        for scored in scored_papers:
            primary = scored.primary_interest
            interest_counts[primary] = interest_counts.get(primary, 0) + 1

        summary_lines = [f"総論文数: {len(scored_papers)}"]
        for interest, count in sorted(interest_counts.items(), key=lambda x: x[1], reverse=True):
            summary_lines.append(f"  • {interest}: {count}件")

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": _rich_text("\n".join(summary_lines)),
            },
        })

        # Top recommended
        if scored_papers:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": _rich_text("⭐ 注目論文 TOP 5"),
                },
            })

        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {},
        })

        return blocks

    def post_weekly_review(
        self, scored_papers: list[RelevanceScore], days: int = 7, max_papers: int = 20
    ) -> str:
        """Post weekly review to Notion database.

        Returns the URL of the created page.
        """
        if not self.database_id:
            raise ValueError(
                "NOTION_DATABASE_ID is required. "
                "Set it in .env or as an environment variable."
            )

        # Build page properties
        properties = {
            "タイトル": {
                "title": _rich_text(self._week_label()),
            },
            "期間": {
                "rich_text": _rich_text(self._date_range_str(days)),
            },
            "論文数": {
                "number": len(scored_papers),
            },
            "ステータス": {
                "select": {"name": "新規"},
            },
        }

        # Build page content blocks
        top_papers = scored_papers[:max_papers]
        children = self._build_summary_blocks(top_papers)
        for rank, scored in enumerate(top_papers, 1):
            paper_blocks = self._build_paper_blocks(scored, rank)
            children.extend(paper_blocks)

        # Notion API limits children to 100 blocks per request
        # Split if needed
        first_batch = children[:100]
        remaining = children[100:]

        try:
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=first_batch,
            )
            page_id = page["id"]
            page_url = page.get("url", "")

            # Append remaining blocks if any
            for i in range(0, len(remaining), 100):
                batch = remaining[i:i + 100]
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=batch,
                )

            logger.info(f"Posted weekly review to Notion: {page_url}")
            return page_url

        except APIResponseError as e:
            logger.error(f"Notion API error: {e}")
            raise

    def verify_connection(self) -> bool:
        """Verify that the Notion integration is properly configured."""
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            title_parts = db.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            logger.info(f"Connected to Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
