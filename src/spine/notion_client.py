"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue with ★ interest-area papers first,
followed by other papers.
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

SPINE_DATABASE_ID = "cec3526e-3831-4769-a814-d8993576ad5e"


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
        self.database_id = config.spine_notion_database_id or SPINE_DATABASE_ID

    # ── Duplicate detection ────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
        """Fetch all PMIDs already posted in the spine database."""
        pmids: set[str] = set()
        has_more = True
        start_cursor = None

        while has_more:
            try:
                time.sleep(self.RATE_LIMIT_DELAY)
                kwargs = {"database_id": self.database_id, "page_size": 100}
                if start_cursor:
                    kwargs["start_cursor"] = start_cursor

                resp = self.client.databases.query(**kwargs)
                for page in resp.get("results", []):
                    props = page.get("properties", {})
                    for prop_name in ("Papers (list)", "Body (JP)"):
                        prop = props.get(prop_name, {})
                        text = _extract_text(prop.get("rich_text", []))
                        pmids.update(re.findall(r"PMID:\s*(\d+)", text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")
            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in spine database")
        return pmids

    # ── Build newsletter content ───────────────────────────────────

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
        comment: str,
        scored_papers: list[SpineScoredArticle],
        duplicates_removed: int,
        days: int = 7,
    ) -> str:
        starred = [s for s in scored_papers if s.is_starred]
        date_range = self._date_range_str(days)
        lines = [
            comment,
            "",
            f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件 "
            f"(★関心領域: {len(starred)}件)",
        ]
        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"
        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers[:15]:
            star = "★ " if s.is_starred else ""
            topic = f"[{', '.join(s.star_topics)}] " if s.is_starred else ""
            lines.append(
                f"• {star}{topic}{s.paper.title[:100]} "
                f"({s.paper.first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _format_paper_section(
        self, rank: int, s: SpineScoredArticle, starred: bool
    ) -> str:
        p = s.paper
        prefix = "★ " if starred else ""
        topic_line = ""
        if s.star_topics:
            topic_line = f"関心領域: {', '.join(s.star_topics)}\n"
        if s.general_topics:
            topic_line += f"Topics: {', '.join(s.general_topics)}"

        title_line = p.title
        if p.title_ja:
            title_line += f"\n邦題: {p.title_ja}"

        section = [
            f"── {prefix}#{rank} ──",
            title_line,
            f"筆頭著者: {p.first_author}",
        ]
        if p.first_affiliation:
            section.append(f"施設: {p.first_affiliation[:200]}")
        section.append(f"ジャーナル: {p.journal_info} | {p.pub_date}")
        if p.doi:
            section.append(f"DOI: {p.doi}")
        section.append(f"PMID: {p.pmid} | {p.url}")
        if topic_line.strip():
            section.append(topic_line.strip())
        section.append("")
        if p.summary_ja:
            section.append(p.summary_ja)
        elif p.abstract:
            excerpt = p.abstract[:400]
            if len(p.abstract) > 400:
                excerpt += "..."
            section.append(excerpt)

        return "\n".join(section)

    def _build_body(self, scored_papers: list[SpineScoredArticle]) -> str:
        starred = [s for s in scored_papers if s.is_starred]
        unstarred = [s for s in scored_papers if not s.is_starred]

        sections = []
        rank = 1

        if starred:
            sections.append("━━━ ★ 関心領域の論文 ━━━")
            for s in starred:
                sections.append(self._format_paper_section(rank, s, starred=True))
                rank += 1

        if unstarred:
            sections.append("\n━━━ 関心領域外の論文 ━━━")
            for s in unstarred:
                sections.append(self._format_paper_section(rank, s, starred=False))
                rank += 1

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers:
            p = s.paper
            star = "★ " if s.is_starred else ""
            parts = [f"• {star}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(
        self, scored_papers: list[SpineScoredArticle]
    ) -> list[str]:
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.all_topics)
        return sorted(all_topics)

    # ── Build rich page blocks ─────────────────────────────────────

    def _build_page_blocks(
        self,
        scored_papers: list[SpineScoredArticle],
        intro: str,
    ) -> list[dict]:
        blocks = []

        blocks.append(
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text(intro),
                    "icon": {"type": "emoji", "emoji": "🦴"},
                },
            }
        )

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        starred = [s for s in scored_papers if s.is_starred]
        unstarred = [s for s in scored_papers if not s.is_starred]

        if starred:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": _rich_text(
                            f"★ 関心領域の論文 ({len(starred)}件)"
                        )
                    },
                }
            )
            self._add_paper_blocks(blocks, starred, start_rank=1, starred=True)

        if unstarred:
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": _rich_text(
                            f"関心領域外の論文 ({len(unstarred)}件)"
                        )
                    },
                }
            )
            self._add_paper_blocks(
                blocks, unstarred, start_rank=len(starred) + 1, starred=False
            )

        return blocks

    def _add_paper_blocks(
        self,
        blocks: list[dict],
        papers: list[SpineScoredArticle],
        start_rank: int,
        starred: bool,
    ) -> None:
        for i, s in enumerate(papers):
            rank = start_rank + i
            p = s.paper
            prefix = "★ " if starred else ""

            title_text = f"#{rank} {prefix}{p.title}"
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {"rich_text": _rich_text(title_text[:100])},
                }
            )

            if p.title_ja:
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(f"邦題: {p.title_ja}")},
                    }
                )

            meta_parts = [f"筆頭著者: {p.first_author}"]
            if p.first_affiliation:
                meta_parts.append(f"施設: {p.first_affiliation[:200]}")
            meta_parts.append(f"ジャーナル: {p.journal_info} | {p.pub_date}")
            topics = s.all_topics
            if topics:
                meta_parts.append(f"Topics: {', '.join(topics)}")
            if p.doi:
                meta_parts.append(f"DOI: {p.doi}")

            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _rich_text("\n".join(meta_parts))},
                }
            )

            blocks.append(
                {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {"url": p.url},
                }
            )

            summary = p.summary_ja or (
                p.abstract[:2000] if p.abstract else "（要旨なし）"
            )
            blocks.append(
                {
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": _rich_text("要約・Abstract"),
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": _rich_text(summary)
                                },
                            }
                        ],
                    },
                }
            )

            blocks.append({"object": "block", "type": "divider", "divider": {}})

    # ── Post to Notion ─────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[SpineScoredArticle],
        comment: str,
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly spine newsletter to Notion."""
        if not self.database_id:
            raise ValueError("Spine NOTION_DATABASE_ID is required.")

        if not scored_papers:
            intro = comment or "今週は対象ジャーナルからの新規論文はありませんでした。"
            properties = {
                "Issue": {"title": _rich_text(self._get_issue_label())},
                "Week": {"date": {"start": self._get_week_monday()}},
                "Status": {"status": {"name": "Draft"}},
                "Source": {"select": {"name": "Claude Code"}},
                "Intro (JP)": {"rich_text": _rich_text(intro)},
            }
            page = self.client.pages.create(
                parent={"database_id": self.database_id},
                properties=properties,
            )
            return page.get("url", "")

        intro = self._build_intro(comment, scored_papers, duplicates_removed, days)
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
                batch = remaining[i : i + 100]
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=batch,
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
