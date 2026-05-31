"""Notion API client for 週刊スパイン（メルマガ）database."""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.spine.scorer import ScoredSpinePaper
from src.spine.summarizer import PaperSummary

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
    """Client for posting weekly spine newsletter to Notion."""

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.spine_database_id or SPINE_DATABASE_ID

    # ── Duplicate detection ─────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
        """Fetch all PMIDs already posted in the spine database."""
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

        logger.info(f"Found {len(pmids)} existing PMIDs in Spine Notion DB")
        return pmids

    # ── Smart weekly commentary ─────────────────────────────────────

    def _generate_weekly_comment(
        self,
        scored_papers: list[ScoredSpinePaper],
        duplicates_removed: int,
    ) -> str:
        """Generate a witty opening comment for the week."""
        n = len(scored_papers)
        interest_papers = [s for s in scored_papers if s.is_interest]
        n_interest = len(interest_papers)

        if n == 0:
            return (
                "今週は対象ジャーナルからの新規論文はありませんでした。"
                "脊椎の世界も一休み — 来週に期待しましょう。"
            )

        comments = []

        if n_interest >= 5:
            comments.append(
                "今週は豊作です！ 関心領域に直撃する論文が多数。"
                "コーヒー片手にじっくりどうぞ。"
            )
        elif n_interest >= 3:
            comments.append(
                "今週はなかなかの収穫週。"
                "★付き論文を中心にチェックする価値ありです。"
            )
        elif n_interest >= 1:
            comments.append(
                "今週もコツコツと。★付きが数本 — "
                "気になるものをピックアップしてみてください。"
            )
        elif n >= 15:
            comments.append(
                "今週は論文数は多いものの、関心領域のド直球は少なめ。"
                "意外な発見があるかもしれません。"
            )
        elif n <= 5:
            comments.append(
                "今週は静かめの一週間。"
                "少数精鋭のラインナップをお届けします。"
            )
        else:
            comments.append(
                "今週も脊椎ジャーナルの最新論文をお届けします。"
            )

        if n_interest > 0:
            topics_found = set()
            for s in interest_papers:
                topics_found.update(s.interest_topics)
            comments.append(
                f"関心領域ヒット: {', '.join(sorted(topics_found))}（計{n_interest}件）。"
            )

        if duplicates_removed > 0:
            comments.append(
                f"※ 過去に取り上げた{duplicates_removed}件は除外済みです。"
            )

        return "\n".join(comments)

    # ── Build newsletter content ────────────────────────────────────

    def _get_week_monday(self) -> str:
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return monday.isoformat()

    def _get_issue_label(self) -> str:
        now = datetime.now()
        week_num = now.isocalendar()[1]
        return f"Vol.{week_num} — {now.year}-W{week_num:02d}"

    def _build_intro(
        self,
        scored_papers: list[ScoredSpinePaper],
        duplicates_removed: int,
    ) -> str:
        comment = self._generate_weekly_comment(scored_papers, duplicates_removed)
        date_range = self._date_range_str()
        n_interest = sum(1 for s in scored_papers if s.is_interest)

        lines = [
            comment,
            "",
            f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件（★関心領域: {n_interest}件）",
        ]

        if duplicates_removed > 0:
            lines[-1] += f" | 既出除外: {duplicates_removed}件"

        return "\n".join(lines)

    def _build_highlights(
        self,
        scored_papers: list[ScoredSpinePaper],
        summaries: dict[str, PaperSummary] | None = None,
    ) -> str:
        lines = []
        for s in scored_papers[:15]:
            star = "★ " if s.is_interest else ""
            topics = s.interest_topics if s.is_interest else s.general_topics[:2]
            topic_str = f"[{', '.join(topics)}]" if topics else ""
            title_display = s.paper.title[:80]
            if summaries and s.paper.pmid in summaries:
                ja = summaries[s.paper.pmid].title_ja
                if ja:
                    title_display = f"{s.paper.title[:60]} ({ja[:40]})"
            lines.append(
                f"• {star}{topic_str} {title_display} "
                f"({s.paper.first_author} et al.)"
            )
        return "\n".join(lines)

    def _build_body(
        self,
        scored_papers: list[ScoredSpinePaper],
        summaries: dict[str, PaperSummary] | None = None,
    ) -> str:
        sections = []
        for i, s in enumerate(scored_papers, 1):
            p = s.paper
            star = "★ " if s.is_interest else ""
            topics = s.interest_topics + s.general_topics
            topic_str = ", ".join(topics) if topics else "General"

            section = [
                f"── {star}#{i} ──",
                f"{p.title}",
            ]
            if summaries and p.pmid in summaries and summaries[p.pmid].title_ja:
                section.append(f"（{summaries[p.pmid].title_ja}）")

            section.extend([
                f"{p.first_author} et al. | {p.journal_citation} | {p.pub_date}",
                f"施設: {p.first_affiliation[:150]}" if p.first_affiliation else "",
                f"Topics: {topic_str}",
                f"PMID: {p.pmid}",
            ])
            if p.doi:
                section.append(f"DOI: {p.doi}")

            if summaries and p.pmid in summaries and summaries[p.pmid].abstract_summary:
                section.append(f"\n{summaries[p.pmid].abstract_summary}")
            elif p.abstract:
                excerpt = p.abstract[:400]
                if len(p.abstract) > 400:
                    excerpt += "..."
                section.append(f"\n{excerpt}")

            section = [l for l in section if l]
            sections.append("\n".join(section))

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[ScoredSpinePaper]) -> str:
        lines = []
        for s in scored_papers:
            p = s.paper
            star = "★ " if s.is_interest else ""
            parts = [f"• {star}{p.title}"]
            parts.append(f"  PMID: {p.pmid}")
            if p.doi:
                parts.append(f"  DOI: {p.doi}")
            parts.append(f"  URL: {p.url}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    def _date_range_str(self, days: int = 7) -> str:
        end = datetime.now()
        start = end - timedelta(days=days)
        return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"

    def _collect_all_topics(self, scored_papers: list[ScoredSpinePaper]) -> list[str]:
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.interest_topics)
            all_topics.update(s.general_topics)
        return sorted(all_topics)

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[ScoredSpinePaper],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
        summaries: dict[str, PaperSummary] | None = None,
    ) -> str:
        """Post a weekly spine newsletter issue to the Notion database."""
        if not self.database_id:
            raise ValueError("Spine database ID is required.")

        if not scored_papers:
            intro = self._generate_weekly_comment([], duplicates_removed)
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

        intro = self._build_intro(scored_papers, duplicates_removed)
        highlights = self._build_highlights(scored_papers, summaries)
        body = self._build_body(scored_papers, summaries)
        papers_list = self._build_papers_list(scored_papers)
        all_topics = self._collect_all_topics(scored_papers)

        properties = {
            "Issue": {"title": _rich_text(self._get_issue_label())},
            "Week": {"date": {"start": self._get_week_monday()}},
            "Status": {"status": {"name": "Draft"}},
            "Source": {"select": {"name": "Claude Code"}},
            "Topics": {"multi_select": [{"name": t} for t in all_topics if t]},
            "Intro (JP)": {"rich_text": _rich_text(intro)},
            "Highlights": {"rich_text": _rich_text(highlights)},
            "Body (JP)": {"rich_text": _rich_text(body)},
            "Papers (list)": {"rich_text": _rich_text(papers_list)},
        }

        children = self._build_page_blocks(scored_papers, intro, summaries)

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

    def _build_page_blocks(
        self,
        scored_papers: list[ScoredSpinePaper],
        intro: str,
        summaries: dict[str, PaperSummary] | None = None,
    ) -> list[dict]:
        """Build rich page body blocks."""
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

        # Interest papers section
        interest_papers = [s for s in scored_papers if s.is_interest]
        other_papers = [s for s in scored_papers if not s.is_interest]

        if interest_papers:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("★ 関心領域")},
            })

            for rank, s in enumerate(interest_papers, 1):
                blocks.extend(self._paper_blocks(s, rank, summaries))

            blocks.append({"object": "block", "type": "divider", "divider": {}})

        if other_papers:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": _rich_text("📋 関心領域外")},
            })

            for rank, s in enumerate(other_papers, 1):
                blocks.extend(self._paper_blocks(s, rank, summaries))

        return blocks

    def _paper_blocks(
        self,
        scored: ScoredSpinePaper,
        rank: int,
        summaries: dict[str, PaperSummary] | None = None,
    ) -> list[dict]:
        """Build blocks for a single paper."""
        blocks = []
        p = scored.paper
        star = "★ " if scored.is_interest else ""

        summary = summaries.get(p.pmid) if summaries else None

        # Title heading (with Japanese translation)
        title_text = f"{star}#{rank} {p.title}"
        blocks.append({
            "object": "block",
            "type": "heading_3",
            "heading_3": {"rich_text": _rich_text(title_text[:100])},
        })

        if summary and summary.title_ja:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(f"（{summary.title_ja}）")},
            })

        # Metadata
        topics = scored.interest_topics + scored.general_topics
        topic_str = ", ".join(topics) if topics else "General"
        meta_parts = [
            f"👤 {p.first_author} et al.",
        ]
        if p.first_affiliation:
            meta_parts.append(f"🏥 {p.first_affiliation[:120]}")
        meta_parts.append(f"📖 {p.journal_citation}")
        if p.doi:
            meta_parts.append(f"🔗 DOI: {p.doi}")
        meta_parts.append(f"🏷️ {topic_str}")

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text("\n".join(meta_parts))},
        })

        # Summary (3-5 lines) or abstract excerpt
        if summary and summary.abstract_summary:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(summary.abstract_summary[:2000])},
            })
        elif p.abstract:
            excerpt = p.abstract[:500]
            if len(p.abstract) > 500:
                excerpt += "..."
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(excerpt)},
            })

        # PubMed link
        blocks.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": p.url},
        })

        # Full abstract in toggle
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

    def verify_connection(self) -> bool:
        try:
            db = self.client.databases.retrieve(database_id=self.database_id)
            title_parts = db.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_parts)
            logger.info(f"Connected to Spine Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
