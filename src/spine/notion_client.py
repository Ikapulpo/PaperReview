"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue (newsletter format):
  - Issue (title): e.g. "Vol.15 — 2026-W15"
  - Week (date): Monday of the week
  - Status (status): Draft
  - Source (select): Claude Code
  - Topics (multi_select): aggregated from all papers
  - Intro (JP) (text): witty commentary + summary
  - Highlights (text): bullet-point headlines
  - Body (JP) (text): per-paper summaries
  - Papers (list) (text): title/PMID/DOI/URL list

Papers matching interest areas (★) are listed first, followed by general papers.
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import SpineScoredArticle

logger = logging.getLogger(__name__)

DATABASE_ID = "cec3526e-3831-4769-a814-d8993576ad5e"


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _extract_text(rich_text_list: list) -> str:
    return "".join(
        t.get("plain_text", "") or t.get("text", {}).get("content", "")
        for t in rich_text_list
    )


class SpineNotionClient:
    """Client for posting weekly spine newsletter to Notion."""

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.spine_notion_database_id or DATABASE_ID

    # ── Duplicate detection ────────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
        """Fetch all PMIDs already posted in the database."""
        pmids: set[str] = set()
        has_more = True
        start_cursor = None

        while has_more:
            try:
                time.sleep(self.RATE_LIMIT_DELAY)
                kwargs = {
                    "database_id": self.database_id,
                    "page_size": 100,
                }
                if start_cursor:
                    kwargs["start_cursor"] = start_cursor

                resp = self.client.databases.query(**kwargs)
                for page in resp.get("results", []):
                    props = page.get("properties", {})

                    papers_list_prop = props.get("Papers (list)", {})
                    papers_text = _extract_text(
                        papers_list_prop.get("rich_text", [])
                    )
                    pmids.update(re.findall(r"PMID:\s*(\d+)", papers_text))

                    body_prop = props.get("Body (JP)", {})
                    body_text = _extract_text(body_prop.get("rich_text", []))
                    pmids.update(re.findall(r"PMID:\s*(\d+)", body_text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")

            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in spine Notion DB")
        return pmids

    # ── Build newsletter content ───────────────────────────────────────

    def _get_week_monday(self) -> str:
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def _get_issue_label(self) -> str:
        now = datetime.now()
        week_num = now.isocalendar()[1]
        return f"Vol.{week_num} — {now.year}-W{week_num:02d}"

    def _date_range_str(self, days: int = 7) -> str:
        end = datetime.now()
        start = end - timedelta(days=days)
        return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"

    def _build_intro(
        self,
        weekly_comment: str,
        scored_papers: list[SpineScoredArticle],
        duplicates_removed: int,
        days: int = 7,
    ) -> str:
        date_range = self._date_range_str(days)
        starred = sum(1 for s in scored_papers if s.is_starred)

        lines = [weekly_comment, ""]
        summary = f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件"
        if starred > 0:
            summary += f"（★関心領域: {starred}件）"
        if duplicates_removed > 0:
            summary += f"（既出{duplicates_removed}件を除外）"
        lines.append(summary)

        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers[:10]:
            star = "★ " if s.is_starred else ""
            topics = ", ".join(s.all_topics) if s.all_topics else ""
            topic_str = f"[{topics}] " if topics else ""
            title = s.paper.title_ja or s.paper.title
            lines.append(
                f"• {star}{topic_str}{title[:80]} "
                f"({s.paper.first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _format_paper_body(self, rank: int, s: SpineScoredArticle) -> str:
        """Format a single paper entry for the Body (JP) property."""
        p = s.paper
        star = "★ " if s.is_starred else ""
        interest_str = ", ".join(s.interest_topics) if s.interest_topics else ""
        general_str = ", ".join(s.general_topics) if s.general_topics else ""

        lines = [f"── {star}#{rank} ──"]
        lines.append(p.title)
        if p.title_ja:
            lines.append(f"（{p.title_ja}）")
        lines.append(f"筆頭著者: {p.first_author}")
        if p.affiliation:
            lines.append(f"施設: {p.affiliation[:200]}")
        lines.append(f"ジャーナル: {p.journal_vol_issue}")
        lines.append(f"PMID: {p.pmid} | {p.url}")
        if p.doi:
            lines.append(f"DOI: {p.doi}")

        topics = []
        if interest_str:
            topics.append(f"★{interest_str}")
        if general_str:
            topics.append(general_str)
        if topics:
            lines.append(f"Topics: {' / '.join(topics)}")

        if p.summary_ja:
            lines.append(f"\n{p.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:300]
            if len(p.abstract) > 300:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_body(self, scored_papers: list[SpineScoredArticle]) -> str:
        sections = []
        for i, s in enumerate(scored_papers, 1):
            sections.append(self._format_paper_body(i, s))
        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers:
            p = s.paper
            star = "★" if s.is_starred else ""
            parts = [f"• {star}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(self, scored_papers: list[SpineScoredArticle]) -> list[str]:
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.all_topics)
        return sorted(all_topics)

    # ── Page blocks (rich body) ────────────────────────────────────────

    def _build_page_blocks(
        self,
        scored_papers: list[SpineScoredArticle],
        intro: str,
    ) -> list[dict]:
        blocks = []

        # Intro callout
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(intro),
                "icon": {"type": "emoji", "emoji": "🦴"},
            },
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # ★ Interest area section
        starred = [s for s in scored_papers if s.is_starred]
        non_starred = [s for s in scored_papers if not s.is_starred]

        if starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域の論文")},
            })

            for rank, s in enumerate(starred, 1):
                blocks.extend(self._paper_blocks(rank, s, starred=True))

            blocks.append({"object": "block", "type": "divider", "divider": {}})

        # General section
        if non_starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("関心領域外の論文")},
            })

            start_rank = len(starred) + 1
            for rank, s in enumerate(non_starred, start_rank):
                blocks.extend(self._paper_blocks(rank, s, starred=False))

        return blocks

    def _paper_blocks(
        self, rank: int, s: SpineScoredArticle, starred: bool
    ) -> list[dict]:
        """Build Notion blocks for a single paper."""
        p = s.paper
        blocks = []

        # Title
        star = "★ " if starred else ""
        heading = f"{star}#{rank} {p.title}"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(heading[:2000])},
        })

        # Japanese title
        if p.title_ja:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(f"（{p.title_ja}）")},
            })

        # Metadata
        meta_lines = [f"筆頭著者: {p.first_author}"]
        if p.affiliation:
            meta_lines.append(f"施設: {p.affiliation[:300]}")
        meta_lines.append(f"ジャーナル: {p.journal_vol_issue}")
        if p.doi:
            meta_lines.append(f"DOI: {p.doi}")

        topics = []
        if s.interest_topics:
            topics.append(f"★ {', '.join(s.interest_topics)}")
        if s.general_topics:
            topics.append(", ".join(s.general_topics))
        if topics:
            meta_lines.append(f"Topics: {' / '.join(topics)}")

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text("\n".join(meta_lines))},
        })

        # PubMed link
        blocks.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": p.url},
        })

        # Summary or abstract
        summary_text = p.summary_ja if p.summary_ja else ""
        if not summary_text and p.abstract:
            summary_text = p.abstract[:2000]

        if summary_text:
            toggle_label = "要旨（日本語要約）" if p.summary_ja else "Abstract"
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text(toggle_label),
                    "children": [{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(summary_text[:2000])},
                    }],
                },
            })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        return blocks

    # ── Post to Notion ─────────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[SpineScoredArticle],
        weekly_comment: str = "",
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly newsletter issue to the Notion database."""
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        if not scored_papers:
            fallback = weekly_comment or (
                "今週は対象ジャーナルからの新規論文はありませんでした。"
            )
            properties = {
                "Issue": {"title": _rich_text(self._get_issue_label())},
                "Week": {"date": {"start": self._get_week_monday()}},
                "Status": {"status": {"name": "Draft"}},
                "Source": {"select": {"name": "Claude Code"}},
                "Intro (JP)": {"rich_text": _rich_text(fallback)},
            }
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
            )
            return page.get("url", "")

        intro = self._build_intro(
            weekly_comment, scored_papers, duplicates_removed, days
        )
        highlights = self._build_highlights(scored_papers)
        body = self._build_body(scored_papers)
        papers_list = self._build_papers_list(scored_papers)
        all_topics = self._collect_all_topics(scored_papers)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Topics": {"multi_select": [{"name": t} for t in all_topics]},
            "Intro (JP)": {"rich_text": _rich_text(intro)},
            "Highlights": {"rich_text": _rich_text(highlights)},
            "Body (JP)": {"rich_text": _rich_text(body)},
            "Papers (list)": {"rich_text": _rich_text(papers_list)},
        }

        children = self._build_page_blocks(scored_papers, intro)

        try:
            time.sleep(self.RATE_LIMIT_DELAY)
            first_batch = children[:100]
            remaining = children[100:]

            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
                children=first_batch,
            )
            page_id = page["id"]
            page_url = page.get("url", "")

            for i in range(0, len(remaining), 100):
                time.sleep(self.RATE_LIMIT_DELAY)
                batch = remaining[i:i + 100]
                self.client.blocks.children.append(
                    block_id=page_id, children=batch,
                )

            logger.info(f"Posted spine weekly issue to Notion: {page_url}")
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
