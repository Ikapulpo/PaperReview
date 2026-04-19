"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue with ★-grouped layout:
  ★ papers (interest areas) at top, then remaining papers.
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
                    for field_name in ("Papers (list)", "Body (JP)"):
                        prop = props.get(field_name, {})
                        text = _extract_text(prop.get("rich_text", []))
                        pmids.update(re.findall(r"PMID:\s*(\d+)", text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")

            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion DB")
        return pmids

    # ── Smart weekly commentary ─────────────────────────────────────

    def _generate_weekly_comment(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        n_total = len(starred) + len(unstarred)
        n_starred = len(starred)

        if n_total == 0:
            return (
                "今週は対象ジャーナルからの新規論文はありませんでした。"
                "静かな一週間ですが、次号をお楽しみに。"
            )

        parts = []

        if n_starred >= 5:
            parts.append(
                "今週は関心領域に該当する論文が多数！ じっくりチェックしてみてください。"
            )
        elif n_starred >= 2:
            parts.append(
                "今週は関心領域に刺さる論文がいくつか出ています。★マーク論文を優先的にどうぞ。"
            )
        elif n_starred == 1:
            parts.append(
                "今週は関心領域の★論文が1件。サクッと目を通しておきたい内容です。"
            )
        elif n_total >= 10:
            parts.append(
                "今週は論文数が多めですが、関心領域への直撃は少なめ。"
                "それでも脊椎外科のトレンドを掴むには良い週です。"
            )
        elif n_total <= 3:
            parts.append(
                "今週は少なめの号です。年度末や学会シーズンの影響かもしれません。"
            )
        else:
            parts.append("今週も脊椎関連の最新論文をお届けします。")

        area_counts: dict[str, int] = {}
        for s in starred:
            for area in s.interest_areas:
                area_counts[area] = area_counts.get(area, 0) + 1

        if area_counts:
            area_str = "、".join(
                f"{name} {count}件" for name, count in area_counts.items()
            )
            parts.append(f"★領域の内訳: {area_str}。")

        if duplicates_removed > 0:
            parts.append(
                f"\n※ 過去に取り上げた{duplicates_removed}件は除外済みです。"
            )

        return "".join(parts)

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

    def _format_journal_info(self, paper) -> str:
        info = paper.journal
        if paper.volume:
            info += f" {paper.volume}"
            if paper.issue:
                info += f"({paper.issue})"
        return info

    def _build_paper_entry(self, s: SpineScoredArticle, rank: int) -> str:
        p = s.paper
        star = "★ " if s.is_starred else ""
        lines = [f"── {star}#{rank} ──"]

        if s.title_ja:
            lines.append(f"{p.title}")
            lines.append(f"（{s.title_ja}）")
        else:
            lines.append(f"{p.title}")

        lines.append(f"筆頭著者: {p.first_author}")
        if p.affiliation:
            aff_short = p.affiliation[:150]
            if len(p.affiliation) > 150:
                aff_short += "..."
            lines.append(f"施設: {aff_short}")
        lines.append(f"ジャーナル: {self._format_journal_info(p)}")
        if p.doi:
            lines.append(f"DOI: {p.doi}")
        lines.append(f"PMID: {p.pmid}")

        if s.is_starred:
            lines.append(f"関心領域: {', '.join(s.interest_areas)}")

        if s.summary_ja:
            lines.append(f"\n{s.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:400]
            if len(p.abstract) > 400:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_intro(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
        days: int,
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        comment = self._generate_weekly_comment(
            starred, unstarred, total_before_dedup, duplicates_removed
        )
        date_range = self._date_range_str(days)
        n_total = len(starred) + len(unstarred)
        line = f"検索期間: {date_range} | 全{n_total}件（★{len(starred)}件）"
        if duplicates_removed > 0:
            line += f" | 既出{duplicates_removed}件除外"
        return f"{comment}\n\n{line}"

    def _build_highlights(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        lines = []
        for s in starred:
            areas = ", ".join(s.interest_areas)
            title = s.title_ja or s.paper.title[:80]
            lines.append(f"★[{areas}] {title} ({s.paper.first_author})")
        for s in unstarred[:10 - len(starred)]:
            title = s.title_ja or s.paper.title[:80]
            lines.append(f"• {title} ({s.paper.first_author})")
        return "\n".join(lines)

    def _build_body(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        sections = []
        rank = 1
        for s in starred:
            sections.append(self._build_paper_entry(s, rank))
            rank += 1
        for s in unstarred:
            sections.append(self._build_paper_entry(s, rank))
            rank += 1
        return "\n\n".join(sections)

    def _build_papers_list(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        lines = []
        for s in starred + unstarred:
            p = s.paper
            star = "★ " if s.is_starred else ""
            parts = [f"{star}• {p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> list[str]:
        all_topics = set()
        for s in starred + unstarred:
            all_topics.update(s.all_topics)
        return sorted(all_topics)

    # ── Page blocks ─────────────────────────────────────────────────

    def _build_paper_blocks(self, s: SpineScoredArticle, rank: int) -> list[dict]:
        p = s.paper
        blocks = []

        star = "★ " if s.is_starred else ""
        heading = f"{star}#{rank} {p.title}"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(heading[:100])},
        })

        if s.title_ja:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [
                    {"type": "text", "text": {"content": f"（{s.title_ja}）"},
                     "annotations": {"italic": True}},
                ]},
            })

        meta_lines = [f"筆頭著者: {p.first_author}"]
        if p.affiliation:
            meta_lines.append(f"施設: {p.affiliation[:150]}")
        meta_lines.append(f"ジャーナル: {self._format_journal_info(p)} | {p.pub_date}")
        if p.doi:
            meta_lines.append(f"DOI: {p.doi}")
        if s.is_starred:
            meta_lines.append(f"関心領域: {', '.join(s.interest_areas)}")

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text("\n".join(meta_lines))},
        })

        blocks.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": p.url},
        })

        summary_text = s.summary_ja or ""
        if not summary_text and p.abstract:
            summary_text = p.abstract[:2000]

        if summary_text:
            toggle_title = "要約" if s.summary_ja else "Abstract"
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text(toggle_title),
                    "children": [{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(summary_text)},
                    }],
                },
            })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        return blocks

    def _build_page_blocks(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
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

        if starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域の論文")},
            })

            rank = 1
            for s in starred:
                blocks.extend(self._build_paper_blocks(s, rank))
                rank += 1

        if unstarred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("その他の論文")},
            })
            rank = len(starred) + 1
            for s in unstarred:
                blocks.extend(self._build_paper_blocks(s, rank))
                rank += 1

        return blocks

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        if not starred and not unstarred:
            intro = self._generate_weekly_comment(
                [], [], total_before_dedup, duplicates_removed
            )
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

        intro = self._build_intro(
            starred, unstarred, days, total_before_dedup, duplicates_removed
        )
        highlights = self._build_highlights(starred, unstarred)
        body = self._build_body(starred, unstarred)
        papers_list = self._build_papers_list(starred, unstarred)
        all_topics = self._collect_all_topics(starred, unstarred)

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

        children = self._build_page_blocks(starred, unstarred, intro)

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
