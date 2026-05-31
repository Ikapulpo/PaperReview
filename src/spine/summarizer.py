"""AI-powered title translation and abstract summarization for spine papers.

Uses the Anthropic API (Claude Haiku) to generate:
  - Japanese translation of English paper titles
  - 3-5 line Japanese summary of the abstract
"""

import logging
import os
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PaperSummary:
    title_ja: str
    abstract_summary: str


def _get_client():
    try:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        return anthropic.Anthropic(api_key=api_key)
    except ImportError:
        logger.debug("anthropic package not installed; skipping AI summarization")
        return None


def summarize_paper(title: str, abstract: str, journal: str) -> PaperSummary | None:
    """Translate title and summarize abstract using Claude Haiku."""
    client = _get_client()
    if client is None:
        return None

    prompt = (
        "あなたは脊椎外科の専門家です。以下の英語論文について、2つの情報を返してください。\n\n"
        f"タイトル: {title}\n"
        f"ジャーナル: {journal}\n"
        f"アブストラクト: {abstract[:3000]}\n\n"
        "以下のフォーマットで回答してください（余計な前置きは不要）:\n\n"
        "TITLE_JA: （タイトルの自然な日本語訳。括弧は使わず1行で）\n\n"
        "SUMMARY: （アブストラクトの内容を日本語で3〜5行に要約。"
        "研究の目的・方法・主要な結果・結論を簡潔に。箇条書きではなく文章で）"
    )

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text

        title_ja = ""
        summary = ""

        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("TITLE_JA:"):
                title_ja = stripped[len("TITLE_JA:"):].strip()
            elif stripped.startswith("SUMMARY:"):
                summary = stripped[len("SUMMARY:"):].strip()

        if not summary and "SUMMARY:" in text:
            parts = text.split("SUMMARY:")
            if len(parts) > 1:
                summary = parts[1].strip()

        if not title_ja and "TITLE_JA:" in text:
            parts = text.split("TITLE_JA:")
            if len(parts) > 1:
                title_ja_section = parts[1].split("SUMMARY:")[0] if "SUMMARY:" in parts[1] else parts[1]
                title_ja = title_ja_section.strip()

        if title_ja or summary:
            return PaperSummary(title_ja=title_ja, abstract_summary=summary)
        return None

    except Exception as e:
        logger.warning(f"AI summarization failed: {e}")
        return None


def batch_summarize(papers: list, delay: float = 0.5) -> dict[str, PaperSummary]:
    """Summarize multiple papers. Returns dict keyed by PMID."""
    client = _get_client()
    if client is None:
        logger.info("AI summarization unavailable (no ANTHROPIC_API_KEY or anthropic package)")
        return {}

    results = {}
    for paper in papers:
        summary = summarize_paper(paper.title, paper.abstract, paper.journal)
        if summary:
            results[paper.pmid] = summary
        time.sleep(delay)

    logger.info(f"AI summarized {len(results)}/{len(papers)} papers")
    return results
