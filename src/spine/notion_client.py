"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue:
  - Issue (title): e.g. "Vol.15 — 2026-W15"
  - Week (date): Monday of the week
  - Status (status): Draft
  - Source (select): Claude Code
  - Intro (JP) (text): smart commentary + summary
  - Body (JP) (text): per-paper summaries
  - Papers (list) (text): title/PMID/DOI list
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import ScoredSpinePaper

logger = logging.getLogger(__name__)


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _rich_text_long(content: str) -> list[dict]:
    """Split long content into multiple rich_text segments (Notion 2000-char limit per segment)."""
    if not content:
        return []
    segments = []
    for i in range(0, len(content), 2000):
        segments.append({"type": "text", "text": {"content": content[i : i + 2000]}})
    return segments


def _extract_text(rich_text_list: list) -> str:
    return "".join(
        t.get("plain_text", "") or t.get("text", {}).get("content", "")
        for t in rich_text_list
    )


WEEKLY_COMMENTS = [
    "今週も脊椎領域の最前線をお届けします。コーヒー片手にどうぞ。",
    "手術の合間にサクッと読める分量にまとめました。",
    "今週のスパイン文献、必読ポイントを凝縮してお届け。",
    "エビデンスは日々更新される——今週のアップデートをチェック。",
    "脊椎外科医の知的好奇心を刺激する一週間分の論文です。",
    "忙しい臨床の合間に、今週の重要論文をキャッチアップ。",
    "Publish or perish の世界から、臨床に活きるエッセンスを抽出しました。",
    "今週も世界の脊椎外科研究は止まらない。注目論文をピックアップ。",
]


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
        self.database_id = config.spine_notion_database_id

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

                    papers_prop = props.get("Papers (list)", {})
                    papers_text = _extract_text(papers_prop.get("rich_text", []))
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

    def _generate_opening_comment(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        duplicates_removed: int,
    ) -> str:
        """Generate a witty, contextual opening comment."""
        import hashlib

        total = len(starred) + len(unstarred)
        week_num = datetime.now().isocalendar()[1]
        idx = int(hashlib.md5(str(week_num).encode()).hexdigest(), 16) % len(WEEKLY_COMMENTS)
        opener = WEEKLY_COMMENTS[idx]

        parts = [opener]

        if starred:
            interest_names = set()
            for s in starred:
                interest_names.update(s.matched_interests)
            parts.append(
                f"\n今週は関心領域に該当する論文が{len(starred)}件ありました"
                f"（{', '.join(sorted(interest_names))}）。★印で上部にまとめています。"
            )
        else:
            parts.append(
                "\n今週は関心領域に直接該当する論文はありませんでしたが、"
                "脊椎領域全般のアップデートをお届けします。"
            )

        if duplicates_removed > 0:
            parts.append(f"\n※ 過去に取り上げた{duplicates_removed}件は除外済みです。")

        return "".join(parts)

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

    def _build_paper_entry(self, paper_scored: ScoredSpinePaper, rank: int) -> str:
        """Build a single paper entry text for the body."""
        p = paper_scored.paper
        star = "★ " if paper_scored.is_starred else ""
        interests = f"[{', '.join(paper_scored.matched_interests)}] " if paper_scored.matched_interests else ""

        lines = [
            f"── #{rank} {star}{interests}──",
            f"{p.title}",
            f"筆頭著者: {p.first_author}",
        ]
        if p.first_affiliation:
            lines.append(f"施設: {p.first_affiliation[:150]}")
        lines.append(f"{p.journal_citation} | {p.pub_date}")
        if p.doi:
            lines.append(f"DOI: {p.doi}")
        lines.append(f"PMID: {p.pmid}")

        if p.abstract:
            summary = p.abstract[:500]
            if len(p.abstract) > 500:
                summary += "..."
            lines.append(f"\n要旨: {summary}")

        return "\n".join(lines)

    def _build_body(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> str:
        """Build full body text with starred papers first."""
        sections = []
        rank = 1

        if starred:
            sections.append("═══ ★ 関心領域論文 ═══\n")
            for s in starred:
                sections.append(self._build_paper_entry(s, rank))
                rank += 1
            sections.append("\n═══ その他の論文 ═══\n")

        for s in unstarred:
            sections.append(self._build_paper_entry(s, rank))
            rank += 1

        return "\n\n".join(sections)

    def _build_papers_list(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> str:
        """Build compact papers list for the property field."""
        lines = []
        for s in starred + unstarred:
            p = s.paper
            star = "★" if s.is_starred else " "
            parts = [f"{star} {p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _build_page_blocks(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        intro: str,
    ) -> list[dict]:
        """Build rich page body blocks for Notion."""
        blocks = []

        # Opening callout
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(intro),
                "icon": {"type": "emoji", "emoji": "🦴"},
            },
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Stats
        total = len(starred) + len(unstarred)
        stats = f"総論文数: {total}件（★関心領域: {len(starred)}件）"
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(stats)},
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        rank = 1

        # Starred section
        if starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域論文")},
            })
            for s in starred:
                blocks.extend(self._paper_blocks(s, rank))
                rank += 1

            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("その他の論文")},
            })

        # Unstarred section
        for s in unstarred:
            blocks.extend(self._paper_blocks(s, rank))
            rank += 1

        return blocks

    def _paper_blocks(self, scored: ScoredSpinePaper, rank: int) -> list[dict]:
        """Build Notion blocks for a single paper."""
        p = scored.paper
        star = "★ " if scored.is_starred else ""
        interests_tag = f" [{', '.join(scored.matched_interests)}]" if scored.matched_interests else ""

        blocks = []
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(f"#{rank} {star}{p.title}")},
        })

        meta_parts = [f"筆頭著者: {p.first_author}"]
        if p.first_affiliation:
            meta_parts.append(f"施設: {p.first_affiliation[:120]}")
        meta_parts.append(f"{p.journal_citation} | {p.pub_date}")
        if p.doi:
            meta_parts.append(f"DOI: {p.doi}")
        if interests_tag:
            meta_parts.append(f"関心領域: {interests_tag.strip()}")

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

        if p.abstract:
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text("要旨サマリー"),
                    "children": [{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(p.abstract[:2000])},
                    }],
                },
            })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        return blocks

    def post_weekly_issue(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly spine newsletter issue to Notion."""
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        intro = self._generate_opening_comment(starred, unstarred, duplicates_removed)
        date_info = f"\n検索期間: {self._date_range_str(days)}"
        intro += date_info

        total = len(starred) + len(unstarred)

        if total == 0:
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

        body = self._build_body(starred, unstarred)
        papers_list = self._build_papers_list(starred, unstarred)
        children = self._build_page_blocks(starred, unstarred, intro)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Intro (JP)": {"rich_text": _rich_text(intro)},
            "Body (JP)": {"rich_text": _rich_text_long(body)},
            "Papers (list)": {"rich_text": _rich_text_long(papers_list)},
        }

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
                    block_id=page_id, children=batch,
                )

            logger.info(f"Posted weekly spine issue to Notion: {page_url}")
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
            logger.info(f"Connected to spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to spine Notion DB: {e}")
            return False
