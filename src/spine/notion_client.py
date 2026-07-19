"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue with papers partitioned into
starred (interest area) and unstarred sections.
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import ScoredSpinePaper
from src.spine.search_query import abbreviate_journal

logger = logging.getLogger(__name__)

SPINE_DATABASE_ID = "cec3526e-3831-4769-a814-d8993576ad5e"

STAR_LABEL = {
    "脊椎外科とAI": "AI",
    "脊椎外科手術の適応評価": "適応",
    "脊椎の基礎研究": "基礎",
    "バイオマテリアル": "材料",
}


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

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.spine_database_id or SPINE_DATABASE_ID

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

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion DB")
        return pmids

    def _generate_weekly_comment(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        total = len(starred) + len(unstarred)

        if total == 0:
            return (
                "今週は脊椎関連の新規論文はありませんでした。"
                "静かな一週間ですが、次週に期待しましょう。"
            )

        parts = []

        parts.append(
            f"今週は脊椎関連6誌から{total}件の新着論文をお届けします。"
        )

        if starred:
            cat_counts: dict[str, int] = {}
            for s in starred:
                for cat in s.star_categories:
                    label = STAR_LABEL.get(cat, cat)
                    cat_counts[label] = cat_counts.get(label, 0) + 1

            parts.append(
                f"★関心領域論文は{len(starred)}件"
            )

            highlights = []
            for label, count in cat_counts.items():
                highlights.append(f"{label}{count}件")
            if highlights:
                parts[-1] += f"（{'、'.join(highlights)}）。"
            else:
                parts[-1] += "。"

            if len(starred) >= 5:
                parts.append("今週は豊作——ぜひチェックを。")
            elif len(starred) >= 3:
                parts.append("注目論文が揃っています。")
        else:
            parts.append(
                "★関心領域に直接該当する論文は少なめですが、"
                "一般的な脊椎外科論文をまとめました。"
            )

        if duplicates_removed > 0:
            parts.append(
                f"\n※ 過去に取り上げた{duplicates_removed}件は除外済みです。"
            )

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

    def _build_intro(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        total_before_dedup: int,
        duplicates_removed: int,
        days: int = 7,
    ) -> str:
        comment = self._generate_weekly_comment(
            starred, unstarred, total_before_dedup, duplicates_removed,
        )
        date_range = self._date_range_str(days)
        total = len(starred) + len(unstarred)

        lines = [comment, "", f"検索期間: {date_range} | 新規論文: {total}件（★{len(starred)}件）"]
        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"

        return "\n".join(lines)

    def _build_highlights(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> str:
        lines = []
        for s in starred[:7]:
            label = STAR_LABEL.get(s.primary_star_category, s.primary_star_category)
            journal = abbreviate_journal(s.paper.journal)
            lines.append(
                f"• ★[{label}] {s.paper.title[:80]} "
                f"({s.paper.first_author} et al., {journal})"
            )
        for s in unstarred[:3]:
            journal = abbreviate_journal(s.paper.journal)
            lines.append(
                f"• {s.paper.title[:80]} "
                f"({s.paper.first_author} et al., {journal})"
            )
        return "\n".join(lines)

    def _build_body(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> str:
        sections = ["── ★関心領域 ──"]
        for i, s in enumerate(starred, 1):
            label = STAR_LABEL.get(s.primary_star_category, s.primary_star_category)
            journal = abbreviate_journal(s.paper.journal)
            excerpt = s.paper.abstract[:120] + "..." if len(s.paper.abstract) > 120 else s.paper.abstract
            sections.append(
                f"#{i} [{label}] {s.paper.first_author} et al. {journal}. PMID:{s.paper.pmid}\n"
                f"{excerpt}"
            )

        sections.append("\n── 関心領域外 ──")
        for i, s in enumerate(unstarred, 1):
            journal = abbreviate_journal(s.paper.journal)
            sections.append(
                f"#{i} {s.paper.first_author}. {journal}. PMID:{s.paper.pmid}"
            )

        return "\n".join(sections)

    def _build_papers_list(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> str:
        lines = []
        for s in starred:
            doi_part = f" DOI:{s.paper.doi}" if s.paper.doi else ""
            lines.append(f"• ★ PMID:{s.paper.pmid}{doi_part}")
        for s in unstarred:
            doi_part = f" DOI:{s.paper.doi}" if s.paper.doi else ""
            lines.append(f"• PMID:{s.paper.pmid}{doi_part}")
        return "\n".join(lines)

    def _collect_all_topics(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
    ) -> list[str]:
        all_topics = set()
        for s in starred + unstarred:
            all_topics.update(s.all_topics)
        return sorted(all_topics)

    def post_weekly_issue(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not self.database_id:
            raise ValueError("SPINE_DATABASE_ID is required.")

        total = len(starred) + len(unstarred)

        if total == 0:
            intro = self._generate_weekly_comment(
                [], [], total_before_dedup, duplicates_removed,
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
            starred, unstarred, total_before_dedup, duplicates_removed, days,
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

    def _build_page_blocks(
        self,
        starred: list[ScoredSpinePaper],
        unstarred: list[ScoredSpinePaper],
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

        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": _rich_text("★ 関心領域")},
        })

        for rank, s in enumerate(starred, 1):
            blocks.extend(self._paper_blocks(s, rank, starred=True))

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": _rich_text("📋 関心領域外")},
        })

        for rank, s in enumerate(unstarred, 1):
            blocks.extend(self._paper_blocks(s, rank, starred=False))

        return blocks

    def _paper_blocks(
        self,
        scored: ScoredSpinePaper,
        rank: int,
        starred: bool,
    ) -> list[dict]:
        blocks = []
        p = scored.paper
        journal = abbreviate_journal(p.journal)

        prefix = f"★#{rank}" if starred else f"#{rank}"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(f"{prefix} {p.title}")},
        })

        star_labels = ", ".join(
            STAR_LABEL.get(c, c) for c in scored.star_categories
        )
        general_labels = ", ".join(scored.general_topics)
        topic_str = ", ".join(filter(None, [star_labels, general_labels]))

        affiliation = ""
        if p.authors and hasattr(p.authors[0], '__contains__'):
            pass
        meta_parts = [
            f"👤 {p.first_author} et al.",
            f"📖 {journal}",
        ]
        if p.doi:
            meta_parts.append(f"🔗 DOI: {p.doi}")
        if topic_str:
            meta_parts.append(f"🏷️ {topic_str}")

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

        if p.abstract and p.abstract != "[Abstract not available]":
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
            logger.info(f"Connected to Spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Spine Notion DB: {e}")
            return False
