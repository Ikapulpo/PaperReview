"""AI summarizer for spine papers using the Anthropic API.

Provides Japanese title translation, abstract summarization,
and weekly commentary generation.
Falls back to simple excerpts when the API key is not configured.
"""

import json
import logging

import requests

from src.config import config
from src.spine.pubmed_client import SpinePaper
from src.spine.scorer import SpineScoredArticle

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"


def _call_api(system: str, user: str, max_tokens: int = 4096) -> str | None:
    api_key = config.anthropic_api_key
    if not api_key:
        return None

    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
    except Exception as e:
        logger.warning(f"Anthropic API call failed: {e}")
        return None


def enrich_papers(papers: list[SpinePaper]) -> None:
    """Add Japanese titles and summaries to papers using the Anthropic API.

    Modifies papers in-place. Falls back to excerpt-based summaries
    when the API is unavailable.
    """
    if not config.anthropic_api_key:
        logger.info("ANTHROPIC_API_KEY not set; using abstract excerpts")
        for p in papers:
            p.title_ja = ""
            if p.abstract:
                p.summary_ja = p.abstract[:500] + ("..." if len(p.abstract) > 500 else "")
            else:
                p.summary_ja = "（要旨なし）"
        return

    batch_size = 10
    for i in range(0, len(papers), batch_size):
        batch = papers[i : i + batch_size]
        _enrich_batch(batch)


def _enrich_batch(papers: list[SpinePaper]) -> None:
    entries = []
    for p in papers:
        abstract_text = p.abstract[:1500] if p.abstract else "(no abstract)"
        entries.append(
            f"PMID: {p.pmid}\nTitle: {p.title}\nAbstract: {abstract_text}"
        )

    system = (
        "あなたは脊椎外科の論文レビューを補助するアシスタントです。"
        "与えられた論文のタイトルを自然な日本語に翻訳し、"
        "要旨を日本語で3〜5行に要約してください。"
        "必ず有効なJSON配列のみを返してください。マークダウンや説明は不要です。"
    )

    user = (
        f"以下の{len(papers)}本の論文について、JSON配列で回答してください。\n"
        "各要素は {\"pmid\": \"...\", \"title_ja\": \"...\", \"summary_ja\": \"...\"} の形式です。\n"
        "summary_jaは改行なしの3〜5文で、要旨の主要な知見を簡潔にまとめてください。\n\n"
        + "\n---\n".join(entries)
    )

    raw = _call_api(system, user, max_tokens=4096)
    if not raw:
        for p in papers:
            p.title_ja = ""
            p.summary_ja = p.abstract[:500] + ("..." if len(p.abstract) > 500 else "") if p.abstract else "（要旨なし）"
        return

    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start >= 0 and end > start:
            results = json.loads(raw[start:end])
        else:
            results = json.loads(raw)

        pmid_map = {str(r["pmid"]): r for r in results}
        for p in papers:
            if p.pmid in pmid_map:
                p.title_ja = pmid_map[p.pmid].get("title_ja", "")
                p.summary_ja = pmid_map[p.pmid].get("summary_ja", "")
            else:
                p.title_ja = ""
                p.summary_ja = p.abstract[:500] + "..." if p.abstract else "（要旨なし）"
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Failed to parse AI response: {e}")
        for p in papers:
            p.title_ja = ""
            p.summary_ja = p.abstract[:500] + "..." if p.abstract else "（要旨なし）"


def generate_weekly_comment(
    scored_papers: list[SpineScoredArticle],
    total_before_dedup: int,
    duplicates_removed: int,
) -> str:
    """Generate a witty, engaging opening comment for the weekly newsletter."""
    n = len(scored_papers)
    starred = [s for s in scored_papers if s.is_starred]

    journal_counts: dict[str, int] = {}
    for s in scored_papers:
        j = s.paper.journal
        journal_counts[j] = journal_counts.get(j, 0) + 1

    star_topic_counts: dict[str, int] = {}
    for s in starred:
        for t in s.star_topics:
            star_topic_counts[t] = star_topic_counts.get(t, 0) + 1

    if config.anthropic_api_key and n > 0:
        journal_info = ", ".join(f"{j}: {c}本" for j, c in sorted(journal_counts.items()))
        star_info = ", ".join(f"{t}: {c}本" for t, c in star_topic_counts.items()) if star_topic_counts else "なし"
        top_titles = "\n".join(f"- {s.paper.title}" for s in scored_papers[:5])

        system = (
            "あなたは脊椎外科の週刊論文レビューの編集者です。"
            "読者は脊椎外科医や研究者です。"
            "気の利いた、読みたくなるような導入コメントを日本語で2〜4文で書いてください。"
            "堅すぎず軽すぎず、知的なユーモアを交えつつ、今週の論文の特徴を伝えてください。"
        )

        user = (
            f"今週の脊椎関連論文レビューの冒頭コメントを書いてください。\n\n"
            f"論文数: {n}本\n"
            f"ジャーナル内訳: {journal_info}\n"
            f"★関心領域: {star_info}\n"
            f"注目論文タイトル:\n{top_titles}\n"
        )
        if duplicates_removed > 0:
            user += f"\n※ 既出{duplicates_removed}件は除外済み"

        result = _call_api(system, user, max_tokens=500)
        if result:
            return result.strip()

    return _fallback_comment(scored_papers, total_before_dedup, duplicates_removed)


def _fallback_comment(
    scored_papers: list[SpineScoredArticle],
    total_before_dedup: int,
    duplicates_removed: int,
) -> str:
    n = len(scored_papers)
    starred = [s for s in scored_papers if s.is_starred]

    if n == 0:
        return (
            "今週は対象ジャーナルからの新規論文はありませんでした。"
            "静かな一週間ですが、次週に期待しましょう。"
        )

    parts = []
    if len(starred) >= 3:
        parts.append("今週は関心領域に合致する論文が多い当たり週です！")
    elif len(starred) >= 1:
        star_names = sorted({t for s in starred for t in s.star_topics})
        parts.append(
            f"今週は関心領域（{', '.join(star_names)}）にマッチする論文があります。"
        )
    elif n >= 10:
        parts.append("今週は論文数が多めの週です。")
    else:
        parts.append("今週も脊椎関連の最新論文をお届けします。")

    if starred:
        top = starred[0]
        parts.append(
            f"注目: 「{top.paper.title[:60]}」"
            f"（{top.paper.first_author} et al., {top.paper.journal}）"
        )

    if duplicates_removed > 0:
        parts.append(f"※ 過去に取り上げた{duplicates_removed}件は除外済みです。")

    return "".join(parts)
