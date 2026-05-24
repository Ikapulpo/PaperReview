"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue:
  - Issue (title): e.g. "Vol.15 — 2026-W15"
  - Week (date): Monday of the week
  - Status (status): Draft
  - Source (select): Claude Code
  - Intro (JP) (text): smart commentary + overall summary
  - Body (JP) (text): per-paper structured summaries
  - Papers (list) (text): title/PMID/DOI list for dedup
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.relevance import ScoredSpinePaper

logger = logging.getLogger(__name__)


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

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion DB")
        return pmids

    def _generate_weekly_comment(
        self,
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
        duplicates_removed: int,
    ) -> str:
        """Generate a witty, contextual opening comment."""
        total = len(interest_papers) + len(other_papers)
        n_interest = len(interest_papers)

        if total == 0:
            return (
                "今週は対象ジャーナルから新規論文の発表がありませんでした。"
                "脊椎の世界も一休み — 来週に期待しましょう。"
            )

        parts = []

        if n_interest >= 5:
            parts.append(
                f"今週は豊作です！ 関心領域に該当する論文が{n_interest}件。"
                "コーヒー片手にじっくりどうぞ。"
            )
        elif n_interest >= 3:
            parts.append(
                f"今週は関心領域の論文が{n_interest}件と充実しています。"
                "気になるものからチェックしてみてください。"
            )
        elif n_interest >= 1:
            parts.append(
                f"今週は関心領域★の論文が{n_interest}件。"
                "全体で{total}件の新規論文をお届けします。".replace("{total}", str(total))
            )
        elif total >= 10:
            parts.append(
                f"今週は{total}件と論文数は多いですが、"
                "関心領域にドンピシャのものは少なめです。トレンドの把握にどうぞ。"
            )
        else:
            parts.append(
                f"今週は{total}件の新規論文をお届けします。"
                "地道にキャッチアップしていきましょう。"
            )

        if interest_papers:
            topics_found = set()
            for s in interest_papers:
                topics_found.update(s.matched_interests)
            parts.append(f"注目テーマ: {', '.join(sorted(topics_found))}")

        if duplicates_removed > 0:
            parts.append(f"（過去に取り上げた{duplicates_removed}件は除外済み）")

        return "\n".join(parts)

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
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
        days: int,
        duplicates_removed: int,
    ) -> str:
        comment = self._generate_weekly_comment(
            interest_papers, other_papers, duplicates_removed
        )
        total = len(interest_papers) + len(other_papers)
        date_range = self._date_range_str(days)

        lines = [
            comment,
            "",
            f"検索期間: {date_range} | 新規論文: {total}件（★関心領域: {len(interest_papers)}件）",
        ]
        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"

        return "\n".join(lines)

    def _format_paper_entry(self, s: ScoredSpinePaper, rank: int) -> str:
        """Format a single paper entry for the Body (JP) field."""
        p = s.paper
        star = "★ " if s.is_interest else ""
        interest_label = ""
        if s.matched_interests:
            interest_label = f"[{', '.join(s.matched_interests)}]\n"

        abstract_summary = p.abstract[:500] if p.abstract else "（要旨なし）"
        if len(p.abstract) > 500:
            abstract_summary += "..."

        lines = [
            f"── #{rank} {star}──",
            interest_label.rstrip("\n") if interest_label else None,
            f"{p.title}",
            f"筆頭著者: {p.first_author}",
            f"施設: {p.affiliation[:200]}" if p.affiliation else None,
            f"ジャーナル: {p.journal_citation}",
            f"DOI: {p.doi}" if p.doi else None,
            f"PMID: {p.pmid}",
            f"",
            f"要旨: {abstract_summary}",
        ]
        return "\n".join(line for line in lines if line is not None)

    def _build_body(
        self,
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
    ) -> str:
        sections = []
        rank = 1

        if interest_papers:
            sections.append("━━━ ★ 関心領域 ━━━")
            for s in interest_papers:
                sections.append(self._format_paper_entry(s, rank))
                rank += 1

        if other_papers:
            sections.append("\n━━━ 関心領域外 ━━━")
            for s in other_papers:
                sections.append(self._format_paper_entry(s, rank))
                rank += 1

        return "\n\n".join(sections)

    def _build_papers_list(
        self,
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
    ) -> str:
        lines = []
        for s in interest_papers + other_papers:
            p = s.paper
            parts = [f"• {s.star_mark}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def post_weekly_issue(
        self,
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly spine newsletter issue to the Notion database."""
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        all_papers = interest_papers + other_papers

        if not all_papers:
            intro = self._generate_weekly_comment([], [], duplicates_removed)
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

        intro = self._build_intro(interest_papers, other_papers, days, duplicates_removed)
        body = self._build_body(interest_papers, other_papers)
        papers_list = self._build_papers_list(interest_papers, other_papers)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Intro (JP)": {"rich_text": _rich_text(intro)},
            "Body (JP)": {"rich_text": _rich_text(body)},
            "Papers (list)": {"rich_text": _rich_text(papers_list)},
        }

        children = self._build_page_blocks(interest_papers, other_papers, intro)

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

    def _build_page_blocks(
        self,
        interest_papers: list[ScoredSpinePaper],
        other_papers: list[ScoredSpinePaper],
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

        # Interest papers section
        if interest_papers:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域")},
            })

            for rank, s in enumerate(interest_papers, 1):
                blocks.extend(self._paper_blocks(s, rank))

            blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Other papers section
        if other_papers:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("関心領域外")},
            })

            start_rank = len(interest_papers) + 1
            for rank, s in enumerate(other_papers, start_rank):
                blocks.extend(self._paper_blocks(s, rank))

        return blocks

    def _paper_blocks(self, s: ScoredSpinePaper, rank: int) -> list[dict]:
        blocks = []
        p = s.paper
        star = "★ " if s.is_interest else ""

        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(f"#{rank} {star}{p.title}")},
        })

        interest_str = f"【{', '.join(s.matched_interests)}】\n" if s.matched_interests else ""
        meta = (
            f"{interest_str}"
            f"筆頭著者: {p.first_author}\n"
            f"施設: {p.affiliation[:150]}\n" if p.affiliation else ""
        )
        meta += f"ジャーナル: {p.journal_citation}\n"
        if p.doi:
            meta += f"DOI: {p.doi}\n"
        meta += f"PMID: {p.pmid}"

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(meta)},
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
                    "rich_text": _rich_text("Abstract / 要旨"),
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
            logger.info(f"Connected to Spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Spine Notion DB: {e}")
            return False
