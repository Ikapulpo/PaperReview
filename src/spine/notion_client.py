"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue, with ★ interest area papers first,
followed by non-starred papers.
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
    """Client for posting weekly spine newsletter issues to Notion."""

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.spine_notion_database_id or SPINE_DATABASE_ID

    # ── Duplicate detection ─────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
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
                    papers_text = _extract_text(papers_list_prop.get("rich_text", []))
                    pmids.update(re.findall(r"PMID:\s*(\d+)", papers_text))

                    body_prop = props.get("Body (JP)", {})
                    body_text = _extract_text(body_prop.get("rich_text", []))
                    pmids.update(re.findall(r"PMID:\s*(\d+)", body_text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")

            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion database")
        return pmids

    # ── Build newsletter content ────────────────────────────────────

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
        scored_papers: list[SpineScoredArticle],
        intro_comment: str,
        days: int = 7,
        duplicates_removed: int = 0,
    ) -> str:
        lines = [intro_comment, ""]
        date_range = self._date_range_str(days)
        starred = [s for s in scored_papers if s.is_starred]
        info = f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件（★{len(starred)}件）"
        if duplicates_removed > 0:
            info += f" | 既出{duplicates_removed}件除外"
        lines.append(info)
        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers[:15]:
            star = "★ " if s.is_starred else ""
            title = s.title_ja if s.title_ja else s.paper.title[:80]
            lines.append(f"• {star}{title} ({s.paper.first_author}, {s.paper.journal})")
        return "\n".join(lines)

    def _format_paper_section(self, rank: int, s: SpineScoredArticle) -> str:
        p = s.paper
        star = "★ " if s.is_starred else ""
        lines = [f"── {star}#{rank} ──"]

        if s.title_ja:
            lines.append(f"{p.title}")
            lines.append(f"（{s.title_ja}）")
        else:
            lines.append(f"{p.title}")

        lines.append(f"{p.first_author} et al.")
        if p.affiliation:
            lines.append(f"施設: {p.affiliation[:150]}")
        lines.append(f"{p.journal_vol_issue} | {p.pub_date}")

        if p.doi:
            lines.append(f"DOI: {p.doi}")
        lines.append(f"PMID: {p.pmid} | {p.url}")

        if s.is_starred:
            lines.append(f"関心領域: {', '.join(s.interest_areas)}")
        if s.general_topics:
            lines.append(f"Topics: {', '.join(s.general_topics)}")

        if s.summary_ja:
            lines.append(f"\n{s.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:400]
            if len(p.abstract) > 400:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_body(self, scored_papers: list[SpineScoredArticle]) -> str:
        sections = []
        starred = [s for s in scored_papers if s.is_starred]
        unstarred = [s for s in scored_papers if not s.is_starred]

        if starred:
            sections.append("━━━ ★ 関心領域 ━━━")
            for i, s in enumerate(starred, 1):
                sections.append(self._format_paper_section(i, s))

        if unstarred:
            sections.append("\n━━━ 関心領域外 ━━━")
            start = len(starred) + 1
            for i, s in enumerate(unstarred, start):
                sections.append(self._format_paper_section(i, s))

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

    # ── Page blocks ─────────────────────────────────────────────────

    def _build_page_blocks(
        self,
        scored_papers: list[SpineScoredArticle],
        intro: str,
    ) -> list[dict]:
        blocks = []

        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(intro),
                "icon": {"type": "emoji", "emoji": "🦴"},
            },
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        starred = [s for s in scored_papers if s.is_starred]
        unstarred = [s for s in scored_papers if not s.is_starred]

        if starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域")},
            })
            blocks.extend(self._paper_blocks(starred, start_rank=1))
            blocks.append({"object": "block", "type": "divider", "divider": {}})

        if unstarred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("関心領域外")},
            })
            blocks.extend(self._paper_blocks(unstarred, start_rank=len(starred) + 1))

        return blocks

    def _paper_blocks(self, papers: list[SpineScoredArticle], start_rank: int) -> list[dict]:
        blocks = []
        for rank, s in enumerate(papers, start_rank):
            p = s.paper
            star = "★ " if s.is_starred else ""

            title_text = f"{star}#{rank} {p.title}"
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(title_text[:100])},
            })

            if s.title_ja:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _rich_text(f"（{s.title_ja}）")},
                })

            meta_parts = [f"{p.first_author} et al."]
            if p.affiliation:
                meta_parts.append(f"施設: {p.affiliation[:120]}")
            meta_parts.append(f"{p.journal_vol_issue} | {p.pub_date}")
            if p.doi:
                meta_parts.append(f"DOI: {p.doi}")

            topic_parts = []
            if s.interest_areas:
                topic_parts.append(f"★ {', '.join(s.interest_areas)}")
            if s.general_topics:
                topic_parts.append(f"Topics: {', '.join(s.general_topics)}")
            if topic_parts:
                meta_parts.append(" | ".join(topic_parts))

            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text("\n".join(meta_parts))},
            })

            blocks.append({
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": p.url},
            })

            summary_text = s.summary_ja if s.summary_ja else ""
            if summary_text:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": _rich_text(summary_text)},
                })

            if p.abstract:
                blocks.append({
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": _rich_text("Abstract (原文)"),
                        "children": [{
                            "object": "block",
                            "type": "paragraph",
                            "paragraph": {"rich_text": _rich_text(p.abstract[:2000])},
                        }],
                    },
                })

            blocks.append({"object": "block", "type": "divider", "divider": {}})

        return blocks

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[SpineScoredArticle],
        intro_comment: str,
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        if not scored_papers:
            intro = (
                "今週は対象ジャーナルからの新規脊椎論文はありませんでした。"
                f"（検索期間: {self._date_range_str(days)}）"
            )
            if duplicates_removed > 0:
                intro += f"\n※ 過去に取り上げた{duplicates_removed}件は除外済みです。"
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

        intro = self._build_intro(scored_papers, intro_comment, days, duplicates_removed)
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
            logger.info(f"Connected to Spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Spine Notion database: {e}")
            return False
