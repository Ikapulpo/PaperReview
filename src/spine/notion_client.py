"""Notion API client for 週刊スパイン（メルマガ）database.

Creates one page per weekly issue containing spine journal papers,
with ★ interest-area papers at the top and the rest below.
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import SpineScoredPaper

logger = logging.getLogger(__name__)


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _rich_text_chunks(content: str) -> list[dict]:
    """Split into 2000-char chunks for Notion rich_text."""
    if not content:
        return []
    chunks = []
    for i in range(0, len(content), 2000):
        chunks.append({"type": "text", "text": {"content": content[i : i + 2000]}})
    return chunks


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
        self.database_id = config.spine_notion_database_id
        if not self.database_id:
            raise ValueError(
                "SPINE_NOTION_DATABASE_ID is required. "
                "Set it in .env or as an environment variable."
            )

    # ── Duplicate detection ─────────────────────────────────────────

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

    # ── Smart weekly commentary ─────────────────────────────────────

    def _generate_weekly_comment(
        self,
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        """Generate a witty opening comment for the weekly issue."""
        n_total = len(starred) + len(unstarred)
        n_star = len(starred)

        if n_total == 0:
            return (
                "今週は対象ジャーナルからの新着論文がありませんでした。"
                "学会シーズンかもしれませんね — 次週に期待しましょう。"
            )

        parts = []

        # Opening with character
        if n_star >= 5:
            parts.append(
                "今週は関心領域の論文が豊作です！ "
                "コーヒー片手にじっくり読みたい一週間。"
            )
        elif n_star >= 3:
            parts.append(
                "今週は注目すべき論文がいくつか出ています。"
                "チェックリストに追加をおすすめします。"
            )
        elif n_star >= 1:
            parts.append(
                "今週は★付き論文あり。"
                "関心領域にヒットした論文を優先的にどうぞ。"
            )
        elif n_total >= 20:
            parts.append(
                "今週は論文数が多めの週です。"
                "関心領域に直接ヒットするものは少なめですが、ざっと目を通しておくと発見があるかも。"
            )
        elif n_total <= 5:
            parts.append(
                "今週はやや静かな週。"
                "少数精鋭を見ていきましょう。"
            )
        else:
            parts.append(
                "今週も脊椎関連の最新論文をお届けします。"
            )

        # Interest area breakdown
        if starred:
            interest_counts: dict[str, int] = {}
            for s in starred:
                for interest in s.matched_interests:
                    interest_counts[interest] = interest_counts.get(interest, 0) + 1

            breakdown = "、".join(
                f"{name} {count}件"
                for name, count in sorted(
                    interest_counts.items(), key=lambda x: x[1], reverse=True
                )
            )
            parts.append(f"★関心領域の内訳: {breakdown}。")

        # Journal breakdown
        journal_counts: dict[str, int] = {}
        for s in starred + unstarred:
            j = s.paper.journal_short
            journal_counts[j] = journal_counts.get(j, 0) + 1
        journal_summary = "、".join(
            f"{j} {c}件" for j, c in sorted(journal_counts.items(), key=lambda x: x[1], reverse=True)
        )
        parts.append(f"収録ジャーナル: {journal_summary}。")

        if duplicates_removed > 0:
            parts.append(f"※ 過去に取り上げた{duplicates_removed}件は除外済み。")

        return "\n".join(parts)

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
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
        total_before_dedup: int,
        duplicates_removed: int,
        days: int,
    ) -> str:
        comment = self._generate_weekly_comment(
            starred, unstarred, total_before_dedup, duplicates_removed
        )
        n_total = len(starred) + len(unstarred)
        date_range = self._date_range_str(days)

        lines = [
            comment,
            "",
            f"検索期間: {date_range} | "
            f"新規論文: {n_total}件（★ {len(starred)}件 / その他 {len(unstarred)}件）",
        ]
        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"

        return "\n".join(lines)

    def _build_paper_section(self, paper_scored: SpineScoredPaper, rank: int, starred: bool) -> str:
        """Build text section for a single paper."""
        p = paper_scored.paper
        star = "★ " if starred else ""
        interests_str = (
            "、".join(paper_scored.matched_interests)
            if paper_scored.matched_interests
            else ""
        )

        lines = [f"── #{rank} {star}──"]

        # Title + Japanese translation
        lines.append(p.title)
        if p.title_ja:
            lines.append(f"（{p.title_ja}）")

        # Metadata
        lines.append(f"筆頭著者: {p.first_author}")
        if p.affiliation:
            lines.append(f"施設: {p.affiliation}")
        lines.append(f"ジャーナル: {p.journal_vol_issue}")
        lines.append(f"論文リンク: {p.url}")

        if interests_str:
            lines.append(f"関心領域: {interests_str}")

        # Summary
        if p.summary_ja:
            lines.append(f"\n{p.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:400]
            if len(p.abstract) > 400:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_body(
        self,
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
    ) -> str:
        sections = []
        rank = 1

        if starred:
            sections.append("━━ ★ 関心領域の論文 ━━")
            for s in starred:
                sections.append(self._build_paper_section(s, rank, starred=True))
                rank += 1

        if unstarred:
            sections.append("\n━━ 関心領域外の論文 ━━")
            for s in unstarred:
                sections.append(self._build_paper_section(s, rank, starred=False))
                rank += 1

        return "\n\n".join(sections)

    def _build_highlights(
        self, starred: list[SpineScoredPaper], unstarred: list[SpineScoredPaper]
    ) -> str:
        lines = []
        for s in starred[:10]:
            interests = "、".join(s.matched_interests)
            title_display = s.paper.title_ja or s.paper.title[:80]
            lines.append(
                f"★ [{interests}] {title_display} "
                f"({s.paper.first_author} et al., {s.paper.journal_short})"
            )
        remaining = 10 - len(starred)
        if remaining > 0:
            for s in unstarred[:remaining]:
                title_display = s.paper.title_ja or s.paper.title[:80]
                lines.append(
                    f"• {title_display} "
                    f"({s.paper.first_author} et al., {s.paper.journal_short})"
                )
        return "\n".join(lines)

    def _build_papers_list(
        self, starred: list[SpineScoredPaper], unstarred: list[SpineScoredPaper]
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
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
    ) -> list[str]:
        """Collect interest area names as Topics for multi_select.

        Uses interest area names from the scorer (脊椎外科とAI etc.) as
        topics. These will be auto-created in Notion if they don't exist.
        """
        all_topics: set[str] = set()
        for s in starred:
            all_topics.update(s.matched_interests)
        return sorted(all_topics)

    # ── Page blocks ─────────────────────────────────────────────────

    def _build_page_blocks(
        self,
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
        intro: str,
    ) -> list[dict]:
        """Build rich Notion page blocks."""
        blocks: list[dict] = []

        # Callout with weekly comment
        blocks.append(
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": _rich_text_chunks(intro),
                    "icon": {"type": "emoji", "emoji": "🦴"},
                },
            }
        )

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # ★ starred section
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

            rank = 1
            for s in starred:
                self._append_paper_blocks(blocks, s, rank, starred=True)
                rank += 1

        # Unstarred section
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

            rank = len(starred) + 1
            for s in unstarred:
                self._append_paper_blocks(blocks, s, rank, starred=False)
                rank += 1

        return blocks

    def _append_paper_blocks(
        self,
        blocks: list[dict],
        scored: SpineScoredPaper,
        rank: int,
        starred: bool,
    ) -> None:
        """Append Notion blocks for a single paper."""
        p = scored.paper
        star = "★ " if starred else ""

        # Title heading
        title_display = p.title
        if p.title_ja:
            title_display = f"{p.title}\n（{p.title_ja}）"

        blocks.append(
            {
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": _rich_text(f"#{rank} {star}{p.title}")
                },
            }
        )

        # Japanese title as separate paragraph if present
        if p.title_ja:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": _rich_text(f"（{p.title_ja}）")
                    },
                }
            )

        # Metadata
        meta_lines = [f"筆頭著者: {p.first_author}"]
        if p.affiliation:
            meta_lines.append(f"施設: {p.affiliation}")
        meta_lines.append(f"ジャーナル: {p.journal_vol_issue}")

        if scored.matched_interests:
            meta_lines.append(f"関心領域: {'、'.join(scored.matched_interests)}")

        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": _rich_text("\n".join(meta_lines))
                },
            }
        )

        # Bookmark to PubMed
        blocks.append(
            {
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": p.url},
            }
        )

        # Summary / abstract toggle
        summary_text = p.summary_ja or (
            p.abstract[:2000] if p.abstract else ""
        )
        if summary_text:
            toggle_title = "要約" if p.summary_ja else "Abstract"
            blocks.append(
                {
                    "object": "block",
                    "type": "toggle",
                    "toggle": {
                        "rich_text": _rich_text(toggle_title),
                        "children": [
                            {
                                "object": "block",
                                "type": "paragraph",
                                "paragraph": {
                                    "rich_text": _rich_text_chunks(
                                        summary_text
                                    )
                                },
                            }
                        ],
                    },
                }
            )

        blocks.append({"object": "block", "type": "divider", "divider": {}})

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        starred: list[SpineScoredPaper],
        unstarred: list[SpineScoredPaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly spine newsletter issue to the Notion database."""
        n_total = len(starred) + len(unstarred)

        if n_total == 0:
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
            starred, unstarred, total_before_dedup, duplicates_removed, days
        )
        highlights = self._build_highlights(starred, unstarred)
        body = self._build_body(starred, unstarred)
        papers_list = self._build_papers_list(starred, unstarred)
        all_interests = self._collect_all_topics(starred, unstarred)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Topics": {
                "multi_select": [{"name": t} for t in all_interests]
            },
            "Intro (JP)": {"rich_text": _rich_text_chunks(intro)},
            "Highlights": {"rich_text": _rich_text_chunks(highlights)},
            "Body (JP)": {"rich_text": _rich_text_chunks(body)},
            "Papers (list)": {"rich_text": _rich_text_chunks(papers_list)},
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
            logger.info(f"Connected to Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
