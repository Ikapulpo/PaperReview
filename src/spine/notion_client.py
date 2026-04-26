"""Notion API client for 週刊スパイン（メルマガ）database."""

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
        self.database_id = config.spine_notion_database_id

    # ── Duplicate detection ─────────────────────────────────────────

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
                    for prop_name in ("Papers (list)", "Body (JP)"):
                        prop = props.get(prop_name, {})
                        text = _extract_text(prop.get("rich_text", []))
                        pmids.update(re.findall(r"PMID:\s*(\d+)", text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")
            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion DB")
        return pmids

    # ── Helpers ─────────────────────────────────────────────────────

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

    # ── Build content ───────────────────────────────────────────────

    def _format_journal_info(self, article: SpineScoredArticle) -> str:
        p = article.paper
        parts = [p.journal]
        if p.volume:
            vol_str = p.volume
            if p.issue:
                vol_str += f"({p.issue})"
            parts.append(vol_str)
        return " ".join(parts)

    def _build_intro(
        self,
        smart_comment: str,
        scored: list[SpineScoredArticle],
        duplicates_removed: int,
        days: int,
    ) -> str:
        starred = [s for s in scored if s.is_starred]
        lines = [
            smart_comment,
            "",
            f"検索期間: {self._date_range_str(days)} | 新規論文: {len(scored)}件"
            f"（★関心領域: {len(starred)}件）",
        ]
        if duplicates_removed > 0:
            lines[-1] += f" | 既出{duplicates_removed}件を除外"
        return "\n".join(lines)

    def _build_highlights(self, scored: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored[:12]:
            prefix = "★ " if s.is_starred else ""
            area = f"[{s.interest_areas[0]}] " if s.interest_areas else ""
            lines.append(
                f"• {prefix}{area}{s.paper.title[:90]} "
                f"({s.paper.first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _build_body(self, scored: list[SpineScoredArticle]) -> str:
        sections = []
        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]

        if starred:
            sections.append("═══ ★ 関心領域の論文 ═══\n")
            for i, s in enumerate(starred, 1):
                sections.append(self._format_paper_section(i, s, starred=True))

        if unstarred:
            sections.append("═══ その他の論文 ═══\n")
            offset = len(starred) + 1
            for i, s in enumerate(unstarred, offset):
                sections.append(self._format_paper_section(i, s, starred=False))

        return "\n".join(sections)

    def _format_paper_section(self, rank: int, s: SpineScoredArticle, starred: bool) -> str:
        p = s.paper
        prefix = "★ " if starred else ""
        area_tag = f" [{', '.join(s.interest_areas)}]" if s.interest_areas else ""
        journal_info = self._format_journal_info(s)

        lines = [
            f"── {prefix}#{rank}{area_tag} ──",
            p.title,
        ]
        if s.title_ja:
            lines.append(f"（{s.title_ja}）")
        lines.append(f"{p.first_author} et al. | {p.affiliation[:120] if p.affiliation else 'N/A'}")
        lines.append(f"{journal_info} | {p.pub_date}")
        lines.append(f"PMID: {p.pmid} | {p.url}")
        if p.doi:
            lines.append(f"DOI: {p.doi}")
        if s.abstract_summary:
            lines.append(f"\n{s.abstract_summary}")
        elif p.abstract:
            excerpt = p.abstract[:300]
            if len(p.abstract) > 300:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines) + "\n"

    def _build_papers_list(self, scored: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored:
            p = s.paper
            prefix = "★ " if s.is_starred else ""
            parts = [f"• {prefix}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(self, scored: list[SpineScoredArticle]) -> list[str]:
        all_topics: set[str] = set()
        for s in scored:
            all_topics.update(s.all_topics)
        return sorted(all_topics)

    # ── Page blocks ─────────────────────────────────────────────────

    def _build_page_blocks(
        self,
        scored: list[SpineScoredArticle],
        intro: str,
    ) -> list[dict]:
        blocks: list[dict] = []

        blocks.append({
            "object": "block", "type": "callout",
            "callout": {
                "rich_text": _rich_text(intro),
                "icon": {"type": "emoji", "emoji": "🦴"},
            },
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        starred = [s for s in scored if s.is_starred]
        unstarred = [s for s in scored if not s.is_starred]

        if starred:
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": _rich_text(
                    f"★ 関心領域の論文（{len(starred)}件）"
                )},
            })
            for rank, s in enumerate(starred, 1):
                blocks.extend(self._paper_blocks(rank, s, starred=True))

        if unstarred:
            blocks.append({
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": _rich_text(
                    f"その他の論文（{len(unstarred)}件）"
                )},
            })
            offset = len(starred) + 1
            for rank, s in enumerate(unstarred, offset):
                blocks.extend(self._paper_blocks(rank, s, starred=False))

        return blocks

    def _paper_blocks(self, rank: int, s: SpineScoredArticle, starred: bool) -> list[dict]:
        p = s.paper
        prefix = "★ " if starred else ""
        area_tag = f" [{', '.join(s.interest_areas)}]" if s.interest_areas else ""
        blocks: list[dict] = []

        blocks.append({
            "object": "block", "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(f"{prefix}#{rank}{area_tag} {p.title}")},
        })

        if s.title_ja:
            blocks.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(f"（{s.title_ja}）")},
            })

        journal_info = self._format_journal_info(s)
        meta = (
            f"{p.first_author} et al.\n"
            f"{p.affiliation[:200] if p.affiliation else 'N/A'}\n"
            f"{journal_info} | {p.pub_date}"
        )
        if p.doi:
            meta += f"\nDOI: {p.doi}"
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": _rich_text(meta)},
        })

        blocks.append({
            "object": "block", "type": "bookmark",
            "bookmark": {"url": p.url},
        })

        summary_text = s.abstract_summary or (p.abstract[:2000] if p.abstract else "")
        if summary_text:
            toggle_title = "要約" if s.abstract_summary else "Abstract"
            blocks.append({
                "object": "block", "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text(toggle_title),
                    "children": [{
                        "object": "block", "type": "paragraph",
                        "paragraph": {"rich_text": _rich_text(summary_text)},
                    }],
                },
            })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        return blocks

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored: list[SpineScoredArticle],
        smart_comment: str = "",
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not self.database_id:
            raise ValueError("SPINE_NOTION_DATABASE_ID is required.")

        if not scored:
            fallback = smart_comment or (
                "今週は新規の脊椎関連論文はありませんでした。次週に期待しましょう。"
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

        intro = self._build_intro(smart_comment, scored, duplicates_removed, days)
        highlights = self._build_highlights(scored)
        body = self._build_body(scored)
        papers_list = self._build_papers_list(scored)
        all_topics = self._collect_all_topics(scored)

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

        children = self._build_page_blocks(scored, intro)

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
