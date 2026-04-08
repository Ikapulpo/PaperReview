"""Notion API client for 週刊NKT（メルマガ）database.

Creates one page per weekly issue (newsletter format):
  - Issue (title): e.g. "Vol.15 — 2026-W15"
  - Week (date): Monday of the week
  - Status (status): Draft
  - Source (select): Claude Code
  - Topics (multi_select): aggregated from all papers
  - Intro (JP) (text): smart commentary + overall summary
  - Highlights (text): bullet-point headlines
  - Body (JP) (text): per-paper short summaries
  - Papers (list) (text): title/PMID/DOI/URL list
"""

import logging
import re
import time
from datetime import datetime, timedelta

from notion_client import Client as NotionSDK
from notion_client.errors import APIResponseError

from src.config import config
from src.scorer.relevance import ScoredArticle

logger = logging.getLogger(__name__)

DATABASE_ID = "a1f5b30f-0402-4ddf-a872-c42622d9c27c"


def _rich_text(content: str) -> list[dict]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _extract_text(rich_text_list: list) -> str:
    """Extract plain text from Notion rich_text property."""
    return "".join(
        t.get("plain_text", "") or t.get("text", {}).get("content", "")
        for t in rich_text_list
    )


class NotionClient:
    """Client for posting weekly newsletter issues to Notion."""

    RATE_LIMIT_DELAY = 0.35

    def __init__(self):
        api_key = config.notion_api_key
        if not api_key:
            raise ValueError(
                "NOTION_API_KEY is required. Set it in .env or as an environment variable."
            )
        self.client = NotionSDK(auth=api_key)
        self.database_id = config.notion_database_id or DATABASE_ID

    # ── Duplicate detection ─────────────────────────────────────────

    def get_existing_pmids(self) -> set[str]:
        """Fetch all PMIDs already posted in the database.

        Parses the 'Papers (list)' and 'Body (JP)' properties of all
        existing issues to extract PMIDs.
        """
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

                    # Extract from Papers (list)
                    papers_list_prop = props.get("Papers (list)", {})
                    papers_text = _extract_text(
                        papers_list_prop.get("rich_text", [])
                    )
                    pmids.update(re.findall(r"PMID:\s*(\d+)", papers_text))

                    # Also check Body (JP) as backup
                    body_prop = props.get("Body (JP)", {})
                    body_text = _extract_text(body_prop.get("rich_text", []))
                    pmids.update(re.findall(r"PMID:\s*(\d+)", body_text))

                has_more = resp.get("has_more", False)
                start_cursor = resp.get("next_cursor")

            except APIResponseError as e:
                logger.warning(f"Failed to query existing pages: {e}")
                break

        logger.info(f"Found {len(pmids)} existing PMIDs in Notion")
        return pmids

    # ── Smart weekly commentary ─────────────────────────────────────

    def _generate_weekly_comment(
        self,
        scored_papers: list[ScoredArticle],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        """Generate a smart, contextual opening comment for the week."""
        n = len(scored_papers)
        top_score = scored_papers[0].total_score if scored_papers else 0
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.matched_topics)

        # Count papers with high relevance (score >= 0.20)
        high_relevance = sum(1 for s in scored_papers if s.total_score >= 0.20)

        # ── Determine the "mood" of the week ──

        if n == 0:
            return (
                "今週はNKT関連の新規論文はありませんでした。"
                "静かな一週間ですが、次週に期待しましょう。"
            )

        comment_parts = []

        # Opening: quality assessment
        if top_score >= 0.8 and high_relevance >= 2:
            comment_parts.append(
                "今週は当たり週です！ "
                "研究に直結しそうな良い論文が複数出ています。"
            )
        elif top_score >= 0.5:
            comment_parts.append(
                "今週は注目すべき論文があります。"
                "特にトップの論文はチェックする価値がありそうです。"
            )
        elif top_score >= 0.20 and high_relevance >= 1:
            comment_parts.append(
                "今週は研究に関連しそうな論文がいくつか出ています。"
            )
        elif n >= 5:
            comment_parts.append(
                "今週はNKT論文の数は多いものの、"
                "直接的に関連する論文は少なめです。"
            )
        elif n <= 2:
            comment_parts.append(
                "今週は少なめの週でした。"
                "NKT分野は論文数の波がありますが、次週に期待です。"
            )
        else:
            comment_parts.append(
                "今週もNKT関連の論文をお届けします。"
            )

        # Topic highlights
        lab_core_topics = {
            "iNKT development", "NKT-B cell", "B cell tolerance",
            "Thymus / development", "Osteoimmunology",
        }
        relevant_core = all_topics & lab_core_topics
        if relevant_core:
            comment_parts.append(
                f"当研究室のコアテーマに関連: {', '.join(sorted(relevant_core))}。"
            )

        vaccine_topics = {"Tumor immunity"}
        if vaccine_topics & all_topics:
            vaccine_papers = [
                s for s in scored_papers
                if "Tumor immunity" in s.matched_topics and s.total_score >= 0.15
            ]
            if vaccine_papers:
                comment_parts.append(
                    f"NKTワクチン・細胞治療関連は{len(vaccine_papers)}件。"
                )

        bone_topics = {"Osteoimmunology"}
        if bone_topics & all_topics:
            comment_parts.append(
                "骨免疫学（Osteoimmunology）関連の報告あり — "
                "骨代謝・整形外科研究との接点に注目。"
            )

        # Top paper callout
        if scored_papers and top_score >= 0.20:
            top = scored_papers[0]
            comment_parts.append(
                f"\n一番のおすすめ: 「{top.paper.title[:60]}」"
                f"（{top.paper.first_author} et al., {top.paper.journal}）"
            )

        # Dedup info
        if duplicates_removed > 0:
            comment_parts.append(
                f"\n※ 過去に取り上げた{duplicates_removed}件は除外済みです。"
            )

        return "".join(comment_parts)

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
        scored_papers: list[ScoredArticle],
        total_before_dedup: int,
        duplicates_removed: int,
    ) -> str:
        """Build intro with smart commentary."""
        comment = self._generate_weekly_comment(
            scored_papers, total_before_dedup, duplicates_removed
        )
        date_range = self._date_range_str()

        lines = [comment, "", f"検索期間: {date_range} | 新規論文: {len(scored_papers)}件"]

        if duplicates_removed > 0:
            lines[-1] += f"（既出{duplicates_removed}件を除外）"

        return "\n".join(lines)

    def _build_highlights(self, scored_papers: list[ScoredArticle]) -> str:
        lines = []
        for s in scored_papers[:10]:
            topic_str = f"[{s.primary_topic}]" if s.matched_topics else ""
            lines.append(
                f"• {topic_str} {s.paper.title[:100]} "
                f"({s.paper.first_author} et al., {s.paper.journal})"
            )
        return "\n".join(lines)

    def _build_body(self, scored_papers: list[ScoredArticle]) -> str:
        sections = []
        for i, s in enumerate(scored_papers, 1):
            p = s.paper
            topic_tags = ", ".join(s.matched_topics) if s.matched_topics else "General"

            section = [
                f"── #{i} ──",
                f"{p.title}",
                f"{p.first_author} et al. | {p.journal} | {p.pub_date}",
                f"Topics: {topic_tags} | Score: {s.total_score:.2f}",
                f"PMID: {p.pmid} | {p.url}",
            ]
            if p.doi:
                section.append(f"DOI: {p.doi}")
            if p.abstract:
                excerpt = p.abstract[:300]
                if len(p.abstract) > 300:
                    excerpt += "..."
                section.append(f"\n{excerpt}")

            sections.append("\n".join(section))

        return "\n\n".join(sections)

    def _build_papers_list(self, scored_papers: list[ScoredArticle]) -> str:
        lines = []
        for s in scored_papers:
            p = s.paper
            parts = [f"• {p.title}"]
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

    def _collect_all_topics(self, scored_papers: list[ScoredArticle]) -> list[str]:
        all_topics = set()
        for s in scored_papers:
            all_topics.update(s.matched_topics)
        return sorted(all_topics)

    # ── Post to Notion ──────────────────────────────────────────────

    def post_weekly_issue(
        self,
        scored_papers: list[ScoredArticle],
        days: int = 7,
        total_before_dedup: int = 0,
        duplicates_removed: int = 0,
    ) -> str:
        """Post a weekly newsletter issue to the Notion database."""
        if not self.database_id:
            raise ValueError("NOTION_DATABASE_ID is required.")

        if not scored_papers:
            # No new papers after dedup
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

        intro = self._build_intro(scored_papers, total_before_dedup, duplicates_removed)
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

            logger.info(f"Posted weekly issue to Notion: {page_url}")
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
        scored_papers: list[ScoredArticle],
        intro: str,
    ) -> list[dict]:
        """Build rich page body blocks."""
        blocks = []

        # Weekly comment callout (the smart intro)
        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": _rich_text(intro),
                "icon": {"type": "emoji", "emoji": "💡"},
            },
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Stats heading
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {"rich_text": _rich_text("📊 トピック別サマリ")},
        })

        topic_counts: dict[str, int] = {}
        for s in scored_papers:
            for t in s.matched_topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1

        stats_lines = [f"新規論文数: {len(scored_papers)}"]
        for t, c in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True):
            stats_lines.append(f"  • {t}: {c}件")

        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _rich_text("\n".join(stats_lines))},
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})

        # Each paper
        for rank, s in enumerate(scored_papers, 1):
            p = s.paper
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": _rich_text(f"#{rank} {p.title}")},
            })

            meta = (
                f"{p.first_author} et al. | {p.journal} | {p.pub_date}\n"
                f"Score: {s.total_score:.2f} | "
                f"Topics: {', '.join(s.matched_topics) if s.matched_topics else 'General'}"
            )
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
            logger.info(f"Connected to Notion database: {title}")
            return True
        except APIResponseError as e:
            logger.error(f"Failed to connect to Notion: {e}")
            return False
