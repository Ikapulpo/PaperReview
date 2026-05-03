"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue:
  - ★ papers (interest-area matches) listed first
  - Remaining papers listed after
  - Each paper: title (JP), first author, institution, journal/vol/issue, DOI,
    3-5 line summary
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


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _long_rich_text(content: str) -> list[dict]:
    """Split long text into multiple rich_text segments (Notion 2000-char limit)."""
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


WITTY_OPENERS = [
    "今週も脊椎外科の最前線をお届けします。",
    "脊椎ジャーナルウォッチ、今週のハイライトです。",
    "新しい一週間、新しい知見。今週の脊椎論文をまとめました。",
    "今週もスパインの世界は止まりません。",
    "背骨のように真っ直ぐ、今週の論文をご紹介します。",
    "椎間板のように柔軟に、今週の研究動向をお伝えします。",
    "アライメントを整えるように、今週の文献を整理しました。",
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
        if not self.database_id:
            raise ValueError(
                "SPINE_NOTION_DATABASE_ID is required. Set it in .env or as an environment variable."
            )

    # ── Duplicate detection ────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
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

    # ── Smart weekly commentary ────────────────────────────────────

    def _generate_weekly_comment(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        import hashlib

        total = len(starred) + len(unstarred)

        if total == 0:
            return (
                "今週は対象ジャーナルからの新規論文がありませんでした。"
                "静かな一週間ですが、次週に期待しましょう。"
            )

        parts = []

        week_hash = int(hashlib.md5(datetime.now().strftime("%Y-W%W").encode()).hexdigest(), 16)
        opener = WITTY_OPENERS[week_hash % len(WITTY_OPENERS)]
        parts.append(opener)

        if starred:
            topic_set = set()
            for s in starred:
                topic_set.update(s.matched_topics)
            parts.append(
                f"関心領域に該当する論文が{len(starred)}件見つかりました"
                f"（{', '.join(sorted(topic_set))}）。"
            )
        else:
            parts.append(
                "今週は関心領域にぴったりの論文はありませんでしたが、"
                "幅広いテーマの論文をお届けします。"
            )

        parts.append(f"今週の新規論文数: {total}件。")

        if duplicates_removed > 0:
            parts.append(f"（過去に取り上げた{duplicates_removed}件は除外済み）")

        return "".join(parts)

    # ── Build page content ─────────────────────────────────────────

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

    def _format_paper_block(self, paper, rank: int, starred: bool) -> str:
        p = paper.paper if hasattr(paper, "paper") else paper
        star = "★ " if starred else ""

        lines = [f"── #{rank} {star}──"]

        if p.title_ja:
            lines.append(p.title)
            lines.append(f"（{p.title_ja}）")
        else:
            lines.append(p.title)

        lines.append(f"筆頭著者: {p.first_author}")

        if p.affiliation:
            aff_short = p.affiliation[:150]
            lines.append(f"施設: {aff_short}")

        lines.append(f"ジャーナル: {p.journal_vol_issue}")

        if p.doi:
            lines.append(f"DOI: {p.doi}")

        lines.append(f"PMID: {p.pmid} | {p.url}")

        if starred and hasattr(paper, "matched_topics") and paper.matched_topics:
            lines.append(f"関心領域: {', '.join(paper.matched_topics)}")

        if p.summary_ja:
            lines.append(f"\n{p.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:500]
            if len(p.abstract) > 500:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_body(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        sections = []
        rank = 1

        if starred:
            sections.append("══ 関心領域の論文 ══\n")
            for s in starred:
                sections.append(self._format_paper_block(s, rank, starred=True))
                rank += 1

        if unstarred:
            sections.append("\n══ 関心領域外の論文 ══\n")
            for s in unstarred:
                sections.append(self._format_paper_block(s, rank, starred=False))
                rank += 1

        return "\n\n".join(sections)

    def _build_highlights(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        lines = []
        all_papers = starred + unstarred
        for s in all_papers[:15]:
            star = "★" if s.is_starred else "  "
            topics = f"[{s.primary_topic}] " if s.matched_topics else ""
            lines.append(
                f"{star} {topics}{s.paper.title[:80]} "
                f"({s.paper.first_author}, {s.paper.journal})"
            )
        return "\n".join(lines)

    def _build_papers_list(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
    ) -> str:
        lines = []
        for s in starred + unstarred:
            p = s.paper
            parts = [f"• {p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(
        self,
        starred: list[SpineScoredArticle],
    ) -> list[str]:
        all_topics = set()
        for s in starred:
            all_topics.update(s.matched_topics)
        return sorted(all_topics)

    # ── Notion page blocks ─────────────────────────────────────────

    def _build_page_blocks(
        self,
        starred: list[SpineScoredArticle],
        unstarred: list[SpineScoredArticle],
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

        all_papers = starred + unstarred
        blocks.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": _rich_text(
                        f"📊 今週のサマリ（計{len(all_papers)}件"
                        f" / ★{len(starred)}件）"
                    )
                },
            }
        )

        if starred:
            topic_counts: dict[str, int] = {}
            for s in starred:
                for t in s.matched_topics:
                    topic_counts[t] = topic_counts.get(t, 0) + 1
            stats_lines = [f"★ 関心領域: {len(starred)}件"]
            for t, c in sorted(
                topic_counts.items(), key=lambda x: x[1], reverse=True
            ):
                stats_lines.append(f"  • {t}: {c}件")
            stats_lines.append(f"その他: {len(unstarred)}件")
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": _rich_text("\n".join(stats_lines))
                    },
                }
            )

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        if starred:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": _rich_text("★ 関心領域の論文")
                    },
                }
            )
            blocks.extend(self._paper_blocks(starred, starred=True))

            blocks.append(
                {"object": "block", "type": "divider", "divider": {}}
            )

        if unstarred:
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": _rich_text("関心領域外の論文")
                    },
                }
            )
            blocks.extend(self._paper_blocks(unstarred, starred=False))

        return blocks

    def _paper_blocks(
        self,
        scored_papers: list[SpineScoredArticle],
        starred: bool,
    ) -> list[dict]:
        blocks = []
        for s in scored_papers:
            p = s.paper
            star = "★ " if starred else ""

            title_line = f"{star}{p.title}"
            blocks.append(
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": _rich_text(title_line[:100])
                    },
                }
            )

            meta_lines = []
            if p.title_ja:
                meta_lines.append(f"日本語訳: {p.title_ja}")
            meta_lines.append(f"筆頭著者: {p.first_author}")
            if p.affiliation:
                meta_lines.append(f"施設: {p.affiliation[:150]}")
            meta_lines.append(f"ジャーナル: {p.journal_vol_issue}")
            if p.doi:
                meta_lines.append(f"DOI: {p.doi}")
            if starred and s.matched_topics:
                meta_lines.append(
                    f"関心領域: {', '.join(s.matched_topics)}"
                )

            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": _rich_text("\n".join(meta_lines))
                    },
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
                p.abstract[:2000] if p.abstract else ""
            )
            if summary:
                toggle_label = "要約" if p.summary_ja else "Abstract"
                blocks.append(
                    {
                        "object": "block",
                        "type": "toggle",
                        "toggle": {
                            "rich_text": _rich_text(toggle_label),
                            "children": [
                                {
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": _rich_text(
                                            summary[:2000]
                                        )
                                    },
                                }
                            ],
                        },
                    }
                )

            blocks.append(
                {"object": "block", "type": "divider", "divider": {}}
            )

        return blocks

    # ── Post to Notion ─────────────────────────────────────────────

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

        intro_comment = self._generate_weekly_comment(
            starred, unstarred, total_before_dedup, duplicates_removed
        )
        date_range = self._date_range_str(days)
        total = len(starred) + len(unstarred)
        intro = f"{intro_comment}\n\n検索期間: {date_range} | 新規論文: {total}件"
        if duplicates_removed > 0:
            intro += f"（既出{duplicates_removed}件を除外）"

        all_topics = self._collect_all_topics(starred)

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

        highlights = self._build_highlights(starred, unstarred)
        body = self._build_body(starred, unstarred)
        papers_list = self._build_papers_list(starred, unstarred)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Intro (JP)": {"rich_text": _long_rich_text(intro)},
            "Highlights": {"rich_text": _long_rich_text(highlights)},
            "Body (JP)": {"rich_text": _long_rich_text(body)},
            "Papers (list)": {"rich_text": _long_rich_text(papers_list)},
        }
        if all_topics:
            properties["Topics"] = {
                "multi_select": [{"name": t} for t in all_topics]
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
            logger.info(f"Connected to Spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Spine Notion: {e}")
            return False
