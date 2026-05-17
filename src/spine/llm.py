"""Optional LLM integration for Japanese translation and summarization.

Uses Anthropic Claude API when ANTHROPIC_API_KEY is available.
Falls back to English-only output when unavailable.
"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic(api_key=api_key)
        return _client
    except ImportError:
        logger.warning("anthropic package not installed. LLM features disabled.")
        return None


def translate_and_summarize_batch(
    papers: list[dict],
) -> dict[str, dict]:
    """Translate titles and summarize abstracts for a batch of papers.

    Args:
        papers: list of {"pmid": str, "title": str, "abstract": str}

    Returns:
        dict mapping pmid to {"title_ja": str, "summary_ja": str}
    """
    client = _get_client()
    if client is None:
        return {}

    if not papers:
        return {}

    papers_text = "\n\n".join(
        f"[PMID:{p['pmid']}]\nTitle: {p['title']}\nAbstract: {p['abstract'][:800]}"
        for p in papers
    )

    prompt = f"""以下の脊椎外科関連の論文について、各論文のタイトルを日本語に翻訳し、
要旨を日本語で3〜5行に要約してください。

{papers_text}

以下のJSON配列で回答してください。余計な説明は不要です:
[
  {{"pmid": "...", "title_ja": "日本語タイトル", "summary_ja": "日本語要約（3〜5行）"}}
]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            logger.warning("LLM response did not contain valid JSON array")
            return {}
        items = json.loads(match.group())
        return {
            item["pmid"]: {
                "title_ja": item.get("title_ja", ""),
                "summary_ja": item.get("summary_ja", ""),
            }
            for item in items
            if "pmid" in item
        }
    except Exception as e:
        logger.warning(f"LLM translation failed: {e}")
        return {}


def process_papers(papers_data: list[dict], batch_size: int = 8) -> dict[str, dict]:
    """Process all papers in batches for translation/summarization.

    Returns dict mapping pmid to {"title_ja": str, "summary_ja": str}
    """
    if not _get_client():
        logger.info("ANTHROPIC_API_KEY not set. Skipping LLM translation.")
        return {}

    results = {}
    for i in range(0, len(papers_data), batch_size):
        batch = papers_data[i:i + batch_size]
        batch_results = translate_and_summarize_batch(batch)
        results.update(batch_results)
        logger.info(f"LLM batch {i // batch_size + 1}: translated {len(batch_results)}/{len(batch)} papers")

    return results


def generate_weekly_intro(
    n_papers: int,
    n_starred: int,
    starred_areas: list[str],
    journals: list[str],
) -> str:
    """Generate a witty weekly introduction comment using LLM.

    Falls back to template-based comment if LLM unavailable.
    """
    client = _get_client()
    if client is None:
        return _template_intro(n_papers, n_starred, starred_areas, journals)

    journal_str = "、".join(sorted(set(journals)))
    areas_str = "、".join(starred_areas) if starred_areas else "なし"

    prompt = f"""あなたは脊椎外科の週刊論文メルマガの編集者です。
今週のメルマガの冒頭に、読者の興味を引く気の利いた導入コメントを1〜3文で書いてください。
堅すぎず、軽妙だけど知的なトーンでお願いします。

今週の情報:
- 新規論文数: {n_papers}件
- ★関心領域にヒットした論文: {n_starred}件
- ヒットした関心領域: {areas_str}
- 掲載ジャーナル: {journal_str}

コメントのみを返してください。"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.warning(f"LLM intro generation failed: {e}")
        return _template_intro(n_papers, n_starred, starred_areas, journals)


def _template_intro(
    n_papers: int,
    n_starred: int,
    starred_areas: list[str],
    journals: list[str],
) -> str:
    """Template-based fallback intro."""
    if n_papers == 0:
        return "今週は対象ジャーナルからの新規論文はありませんでした。静かな一週間です。"

    parts = []
    if n_starred >= 3:
        parts.append(f"今週は豊作です！ ★関心領域に該当する論文が{n_starred}件もあります。")
    elif n_starred >= 1:
        parts.append(f"今週は★関心領域に{n_starred}件のヒットがあります。要チェックです。")
    elif n_papers >= 10:
        parts.append(f"今週は{n_papers}件と論文多めの週です。")
    else:
        parts.append(f"今週は{n_papers}件の新着論文をお届けします。")

    if starred_areas:
        parts.append(f"関心領域: {', '.join(starred_areas)}。")

    return "".join(parts)
