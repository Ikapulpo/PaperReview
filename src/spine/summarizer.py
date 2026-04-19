"""Claude API summarizer for spine papers.

Translates titles to Japanese and summarizes abstracts in 3-5 lines.
Requires ANTHROPIC_API_KEY environment variable.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

BATCH_SIZE = 8


def _build_prompt(papers_batch: list[dict]) -> str:
    parts = [
        "以下の脊椎関連論文について、各論文の:\n"
        "1. タイトルを自然な日本語に翻訳\n"
        "2. 要旨を日本語で3〜5行に要約（臨床的意義がわかるように）\n\n"
        "JSON配列で返してください。各要素は {\"index\": 番号, \"title_ja\": \"...\", \"summary_ja\": \"...\"} の形式で。\n"
        "JSONのみ出力し、他の説明は不要です。\n\n"
    ]
    for i, p in enumerate(papers_batch, 1):
        parts.append(f"--- 論文{i} ---")
        parts.append(f"Title: {p['title']}")
        abstract = p.get("abstract", "")
        if abstract:
            parts.append(f"Abstract: {abstract[:1500]}")
        else:
            parts.append("Abstract: (not available)")
        parts.append("")

    return "\n".join(parts)


def summarize_papers(papers_data: list[dict]) -> list[dict]:
    """Translate titles and summarize abstracts using Claude API.

    Args:
        papers_data: List of dicts with 'title' and 'abstract' keys.

    Returns:
        List of dicts with 'title_ja' and 'summary_ja' keys,
        in the same order as input. Falls back gracefully on error.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set; skipping AI summarization")
        return [{"title_ja": "", "summary_ja": ""} for _ in papers_data]

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; skipping AI summarization")
        return [{"title_ja": "", "summary_ja": ""} for _ in papers_data]

    client = anthropic.Anthropic(api_key=api_key)
    results = []

    for batch_start in range(0, len(papers_data), BATCH_SIZE):
        batch = papers_data[batch_start:batch_start + BATCH_SIZE]
        prompt = _build_prompt(batch)

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]
            parsed = json.loads(text)

            for item in parsed:
                idx = item.get("index", 0) - 1
                if 0 <= idx < len(batch):
                    results.append({
                        "title_ja": item.get("title_ja", ""),
                        "summary_ja": item.get("summary_ja", ""),
                    })
                else:
                    results.append({"title_ja": "", "summary_ja": ""})

            while len(results) < batch_start + len(batch):
                results.append({"title_ja": "", "summary_ja": ""})

        except Exception as e:
            logger.warning(f"AI summarization failed for batch: {e}")
            results.extend(
                [{"title_ja": "", "summary_ja": ""} for _ in batch]
            )

    return results[:len(papers_data)]
