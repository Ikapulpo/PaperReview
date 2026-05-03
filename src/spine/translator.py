"""Optional LLM-based title translation and abstract summarisation.

Uses the Anthropic API (Claude) to:
  - Translate English paper titles into Japanese
  - Summarise abstracts in 3-5 lines of Japanese

Falls back gracefully when ANTHROPIC_API_KEY is unset or the SDK is
not installed.
"""

import json
import logging
import os
import re
import time

from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)


def _try_parse_json(text: str) -> list[dict] | None:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def _truncate_abstract(abstract: str, max_chars: int = 500) -> str:
    if not abstract:
        return ""
    if len(abstract) <= max_chars:
        return abstract
    cut = abstract[:max_chars]
    last_period = cut.rfind(".")
    if last_period > max_chars * 0.5:
        return cut[: last_period + 1]
    return cut + "..."


def _fallback_summary(paper: SpinePaper) -> str:
    return _truncate_abstract(paper.abstract)


def translate_and_summarize(papers: list[SpinePaper]) -> None:
    """Translate titles and summarise abstracts in-place.

    Populates ``paper.title_ja`` and ``paper.summary_ja`` for every paper.
    If the Anthropic API is unavailable, ``title_ja`` stays empty and
    ``summary_ja`` falls back to a truncated abstract.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set — skipping translation")
        for p in papers:
            p.summary_ja = _fallback_summary(p)
        return

    try:
        import anthropic  # noqa: F811
    except ImportError:
        logger.info("anthropic package not installed — skipping translation")
        for p in papers:
            p.summary_ja = _fallback_summary(p)
        return

    client = anthropic.Anthropic(api_key=api_key)

    batch_size = 10
    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        _process_batch(client, batch)
        if i + batch_size < len(papers):
            time.sleep(1.0)


def _process_batch(client, papers: list[SpinePaper]) -> None:
    entries = []
    for idx, p in enumerate(papers):
        abstract_text = p.abstract[:1500] if p.abstract else "N/A"
        entries.append(
            f"[{idx}] PMID: {p.pmid}\n"
            f"Title: {p.title}\n"
            f"Abstract: {abstract_text}"
        )

    prompt = (
        "以下の脊椎外科関連の医学論文について、それぞれ:\n"
        "1. タイトルの日本語訳（title_ja）\n"
        "2. 要旨の日本語要約 3〜5行（summary_ja）\n"
        "をJSON配列で返してください。\n"
        "JSONのみ出力し、他のテキストは不要です。\n\n"
        + "\n\n".join(entries)
        + "\n\n"
        "回答フォーマット:\n"
        '[{"pmid":"...","title_ja":"...","summary_ja":"..."},...]'
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        items = _try_parse_json(text)

        if items:
            pmid_map = {str(item["pmid"]): item for item in items if "pmid" in item}
            for p in papers:
                if p.pmid in pmid_map:
                    p.title_ja = pmid_map[p.pmid].get("title_ja", "")
                    p.summary_ja = pmid_map[p.pmid].get("summary_ja", "")
                if not p.summary_ja:
                    p.summary_ja = _fallback_summary(p)
        else:
            logger.warning("Failed to parse LLM response — using fallback summaries")
            for p in papers:
                p.summary_ja = _fallback_summary(p)

    except Exception as e:
        logger.warning(f"LLM translation failed: {e} — using fallback summaries")
        for p in papers:
            if not p.summary_ja:
                p.summary_ja = _fallback_summary(p)
