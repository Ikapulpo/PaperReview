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

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.spine_database_id or SPINE_DATABASE_ID

    # ── Duplicate detection ────────────────────────────────────────

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
                    for prop_name in ("Papers (list)", "Body (JP)"):
                        prop = props.get(prop_name, {})
                        text = _extract_text(prop.get("rich_text", []))
                        pmids.update(re.findall(r"PMID:\s*(\d+)", text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")

            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine database")
        return pmids

    # ── Content builders ───────────────────────────────────────────

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

    def _format_journal_ref(self, art: SpineScoredArticle) -> str:
        p = art.paper
        ref = p.journal
        if p.volume:
            ref += f", Vol.{p.volume}"
        if p.issue_number:
            ref += f"({p.issue_number})"
        if p.pub_date:
            ref += f", {p.pub_date}"
        return ref

    def _build_intro(
        self,
        weekly_comment: str,
        scored_papers: list[SpineScoredArticle],
        duplicates_removed: int,
        days: int = 7,
    ) -> str:
        date_range = self._date_range_str(days)
        star_count = sum(1 for s in scored_papers if s.is_star)

        lines = [
            weekly_comment, "",
            f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件"
            f"（★関心領域: {star_count}件）",
        ]
        if duplicates_removed > 0:
            lines[-1] += f" | 既出{duplicates_removed}件を除外"

        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers[:15]:
            mark = "★ " if s.is_star else ""
            topic_str = ""
            if s.star_topics:
                topic_str = f"[{', '.join(s.star_topics)}] "
            lines.append(
                f"• {mark}{topic_str}{s.paper.title[:100]} "
                f"({s.paper.first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _build_paper_section(self, rank: int, art: SpineScoredArticle) -> str:
        p = art.paper
        star_mark = "★" if art.is_star else ""
        topic_tag = ""
        if art.star_topics:
            topic_tag = f"【{'／'.join(art.star_topics)}】"

        lines = [f"── #{rank} {star_mark}{topic_tag} ──"]
        lines.append(p.title)
        if art.title_ja:
            lines.append(f"（{art.title_ja}）")

        lines.append(f"筆頭著者: {p.first_author}")
        if p.affiliation:
            aff_short = p.affiliation[:150]
            if len(p.affiliation) > 150:
                aff_short += "..."
            lines.append(f"施設: {aff_short}")

        lines.append(self._format_journal_ref(art))
        if p.doi:
            lines.append(f"DOI: {p.doi}")
        lines.append(f"PMID: {p.pmid}")

        if art.summary_ja:
            lines.append(f"\n{art.summary_ja}")
        elif p.abstract:
            excerpt = p.abstract[:400]
            if len(p.abstract) > 400:
                excerpt += "..."
            lines.append(f"\n{excerpt}")

        return "\n".join(lines)

    def _build_body(self, scored_papers: list[SpineScoredArticle]) -> str:
        starred = [s for s in scored_papers if s.is_star]
        non_starred = [s for s in scored_papers if not s.is_star]

        sections = []
        rank = 1

        if starred:
            sections.append("━━━ ★ 関心領域 ━━━")
            for art in starred:
                sections.append(self._build_paper_section(rank, art))
                rank += 1

        if non_starred:
            sections.append("\n━━━ 関心領域外 ━━━")
            for art in non_starred:
                sections.append(self._build_paper_section(rank, art))
                rank += 1

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[SpineScoredArticle]) -> str:
        lines = []
        for s in scored_papers:
            p = s.paper
            mark = "★ " if s.is_star else ""
            parts = [f"• {mark}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _collect_all_topics(self, scored_papers: list[SpineScoredArticle]) -> list[str]:
        all_topics: set[str] = set()
        for s in scored_papers:
            all_topics.update(s.star_topics)
            all_topics.update(s.general_topics)
        return sorted(all_topics)

    # ── Page blocks ────────────────────────────────────────────────

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

        starred = [s for s in scored_papers if s.is_star]
        non_starred = [s for s in scored_papers if not s.is_star]

        rank = 1

        if starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("⭐ 関心領域")},
            })

            for art in starred:
                blocks.extend(self._paper_blocks(rank, art))
                rank += 1

        if non_starred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("📋 関心領域外")},
            })

            for art in non_starred:
                blocks.extend(self._paper_blocks(rank, art))
                rank += 1

        return blocks

    def _paper_blocks(self, rank: int, art: SpineScoredArticle) -> list[dict]:
        blocks = []
        p = art.paper

        star_mark = "★ " if art.is_star else ""
        topic_tag = ""
        if art.star_topics:
            topic_tag = f"【{'／'.join(art.star_topics)}】"

        title_line = f"#{rank} {star_mark}{topic_tag}{p.title}"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(title_line[:2000])},
        })

        meta_lines = []
        if art.title_ja:
            meta_lines.append(f"（{art.title_ja}）")
        meta_lines.append(f"筆頭著者: {p.first_author}")
        if p.affiliation:
            meta_lines.append(f"施設: {p.affiliation[:200]}")
        meta_lines.append(self._format_journal_ref(art))
        if p.doi:
            meta_lines.append(f"DOI: {p.doi}")

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

        summary = art.summary_ja or ""
        if summary:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(summary[:2000])},
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

    # ── Post to Notion ─────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[SpineScoredArticle],
        weekly_comment: str,
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not self.database_id:
            raise ValueError("SPINE_DATABASE_ID is required.")

        if not scored_papers:
            intro = weekly_comment or "今週は新規論文がありませんでした。"
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
