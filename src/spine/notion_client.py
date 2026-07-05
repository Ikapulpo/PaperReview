"""Notion API client for 週刊スパイン（メルマガ）database."""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import ScoredSpinePaper

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
        self.database_id = SPINE_DATABASE_ID

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

        logger.info(f"Found {len(pmids)} existing PMIDs in spine database")
        return pmids

    def _generate_weekly_comment(
        self,
        scored_papers: list[ScoredSpinePaper],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        n = len(scored_papers)
        starred = [s for s in scored_papers if s.is_starred]
        n_starred = len(starred)

        if n == 0:
            return (
                "今週は対象ジャーナルからの新規論文はありませんでした。"
                "静かな一週間ですが、次週に期待しましょう。"
            )

        parts = []

        if n_starred >= 5:
            parts.append(
                "今週は豊作！ 関心領域に合致する論文が多数あり、"
                "★付き論文を中心にチェックする価値ありです。"
            )
        elif n_starred >= 2:
            parts.append(
                "今週はなかなかの収穫週。"
                "★付き論文を中心にチェックする価値ありです。"
            )
        elif n_starred == 1:
            parts.append(
                "今週は関心領域に1件ヒットあり。"
                "該当論文はぜひチェックを。"
            )
        elif n >= 10:
            parts.append(
                "今週は論文数は多いものの、"
                "関心領域への直接的なヒットはありませんでした。"
            )
        elif n <= 3:
            parts.append(
                "今週は少なめの週でした。次週に期待です。"
            )
        else:
            parts.append(
                "今週も脊椎関連の論文をお届けします。"
            )

        if starred:
            areas = set()
            for s in starred:
                areas.update(s.interest_areas)
            parts.append(
                f"関心領域ヒット: {', '.join(sorted(areas))}"
                f"（計{n_starred}件）。"
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
        scored_papers: list[ScoredSpinePaper],
        days: int,
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        comment = self._generate_weekly_comment(
            scored_papers, total_before_dedup, duplicates_removed
        )
        date_range = self._date_range_str(days)
        starred_count = sum(1 for s in scored_papers if s.is_starred)

        lines = [
            comment, "",
            f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件"
            f"（★関心領域: {starred_count}件）",
        ]
        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"

        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[ScoredSpinePaper]) -> str:
        lines = []
        for s in scored_papers[:10]:
            star = "★ " if s.is_starred else ""
            tags = s.interest_areas if s.is_starred else s.general_topics
            tag_str = f"[{', '.join(tags)}] " if tags else ""
            lines.append(
                f"• {star}{tag_str}{s.paper.title[:100]} "
                f"({s.paper.first_author} et al.)"
            )
        return "\n".join(lines)

    def _build_body(self, scored_papers: list[ScoredSpinePaper]) -> str:
        sections = []
        for i, s in enumerate(scored_papers, 1):
            p = s.paper
            star = "★" if s.is_starred else ""
            tags = s.interest_areas + s.general_topics
            tag_str = ", ".join(tags) if tags else "General"

            section = [
                f"── {star}#{i} ──",
                p.title,
                f"{p.first_author} et al. | {p.journal} | {p.pub_date}",
                f"Topics: {tag_str}",
                f"PMID: {p.pmid} | {p.url}",
            ]
            if p.doi:
                section.append(f"DOI: {p.doi}")
            if p.affiliation:
                section.append(f"施設: {p.affiliation[:200]}")
            if p.abstract:
                excerpt = p.abstract[:300]
                if len(p.abstract) > 300:
                    excerpt += "..."
                section.append(f"\n{excerpt}")
            sections.append("\n".join(section))

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[ScoredSpinePaper]) -> str:
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

    def _collect_all_topics(self, scored_papers: list[ScoredSpinePaper]) -> list[str]:
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.interest_areas)
            all_topics.update(s.general_topics)
        return sorted(all_topics)

    def _build_page_blocks(
        self,
        scored_papers: list[ScoredSpinePaper],
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
            for rank, s in enumerate(starred, 1):
                blocks.extend(self._paper_blocks(s, rank, starred=True))

        if unstarred:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("📋 関心領域外")},
            })
            for rank, s in enumerate(unstarred, 1):
                blocks.extend(self._paper_blocks(s, rank, starred=False))

        return blocks

    def _paper_blocks(
        self, s: ScoredSpinePaper, rank: int, starred: bool
    ) -> list[dict]:
        blocks = []
        p = s.paper
        prefix = "★" if starred else ""
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(f"{prefix}#{rank} {p.title}")},
        })

        meta_lines = [f"👤 {p.first_author} et al."]
        if p.affiliation:
            meta_lines.append(f"🏥 {p.affiliation[:200]}")
        meta_lines.append(f"📖 {p.journal}")
        if p.doi:
            meta_lines.append(f"🔗 DOI: {p.doi}")
        tags = s.interest_areas + s.general_topics
        if tags:
            meta_lines.append(f"🏷️ {', '.join(tags)}")

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

        if p.abstract:
            blocks.append({
                "object": "block",
                "type": "toggle",
                "toggle": {
                    "rich_text": _rich_text("原文 Abstract"),
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
        scored_papers: list[ScoredSpinePaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        if not scored_papers:
            intro = self._generate_weekly_comment(
                [], total_before_dedup, duplicates_removed
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
            scored_papers, days, total_before_dedup, duplicates_removed
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

            logger.info(f"Posted spine issue to Notion: {page_url}")
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
            logger.info(f"Connected to spine database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
