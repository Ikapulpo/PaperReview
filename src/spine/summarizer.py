"""LLM-based enrichment: Japanese title translation and abstract summarization.

Uses the Anthropic Claude API to translate paper titles and generate
concise 3–5 line Japanese summaries of abstracts.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


def _get_anthropic_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "")


def enrich_papers(papers: list) -> list:
    """Translate titles and summarize abstracts for a list of SpinePapers.

    Mutates each paper's ``title_ja`` and ``summary_ja`` fields in-place.
    If the API key is not set or the call fails, falls back to simple
    truncated abstracts and untranslated titles.

    Args:
        papers: list of SpinePaper objects.

    Returns:
        The same list (mutated in-place) for convenience.
    """
    api_key = _get_anthropic_key()
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — skipping LLM enrichment. "
            "Titles will not be translated; abstracts will be truncated."
        )
        _fallback_enrich(papers)
        return papers

    try:
        import anthropic  # noqa: F811
    except ImportError:
        logger.warning(
            "anthropic package not installed — skipping LLM enrichment."
        )
        _fallback_enrich(papers)
        return papers

    # Process in batches to stay within context limits
    batch_size = 15
    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        try:
            _enrich_batch(batch, api_key)
        except Exception as e:
            logger.error(f"LLM enrichment failed for batch {i}: {e}")
            _fallback_enrich(batch)

    return papers


def _enrich_batch(papers: list, api_key: str) -> None:
    """Call Claude API to translate & summarise a batch of papers."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    # Build paper list for prompt
    paper_entries = []
    for idx, p in enumerate(papers):
        abstract_excerpt = p.abstract[:1500] if p.abstract else "(no abstract)"
        paper_entries.append(
            f"[{idx}]\n"
            f"Title: {p.title}\n"
            f"Abstract: {abstract_excerpt}"
        )

    papers_block = "\n\n".join(paper_entries)

    prompt = f"""以下の医学論文について、それぞれ2つの情報を返してください。

1. **title_ja**: 論文タイトルの日本語訳（自然で正確な医学用語を使用）
2. **summary_ja**: 要旨（Abstract）の日本語要約（3〜5行、簡潔に要点をまとめる）

Abstractが無い場合はタイトルから推測して1〜2行の概要を書いてください。

必ず以下のJSON配列形式で返してください。他のテキストは不要です:
[
  {{"idx": 0, "title_ja": "...", "summary_ja": "..."}},
  {{"idx": 1, "title_ja": "...", "summary_ja": "..."}}
]

--- 論文リスト ---
{papers_block}
"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = message.content[0].text.strip()

    # Parse JSON from response (handle markdown code blocks)
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)
        response_text = "\n".join(json_lines)

    results = json.loads(response_text)

    for item in results:
        idx = item.get("idx")
        if idx is not None and 0 <= idx < len(papers):
            papers[idx].title_ja = item.get("title_ja", "")
            papers[idx].summary_ja = item.get("summary_ja", "")


def _fallback_enrich(papers: list) -> None:
    """Fallback: use truncated abstract as summary, no title translation."""
    for p in papers:
        if not p.title_ja:
            p.title_ja = ""  # leave empty — display logic handles this
        if not p.summary_ja and p.abstract:
            # Take first ~300 chars as a rough summary
            excerpt = p.abstract[:300]
            if len(p.abstract) > 300:
                excerpt += "..."
            p.summary_ja = excerpt
