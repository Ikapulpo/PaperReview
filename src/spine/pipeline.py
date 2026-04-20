"""Main pipeline: PubMed search → Dedup → Scoring → Summarize → JSON export.

The pipeline always saves its results to a JSON file under ``data/spine/``.
Notion posting is handled separately — either by the Python SDK
(``notion-client``, requires ``NOTION_API_KEY``) or by Claude Code's
Notion MCP tools, which use a different authentication channel.

Weekly spine paper review for:
  Spine, The Spine Journal, European Spine Journal,
  JNS: Spine, Global Spine Journal, JBJS
"""

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "spine")
PMIDS_FILE = os.path.join(DATA_DIR, "posted_pmids.json")


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_posted_pmids() -> set[str]:
    """Load previously posted PMIDs from local tracking file."""
    if not os.path.exists(PMIDS_FILE):
        return set()
    try:
        with open(PMIDS_FILE) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_posted_pmids(pmids: set[str]):
    """Save posted PMIDs to local tracking file."""
    _ensure_data_dir()
    with open(PMIDS_FILE, "w") as f:
        json.dump(sorted(pmids), f)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def _scored_to_dict(scored_articles) -> list[dict]:
    """Convert scored articles to JSON-serialisable dicts."""
    results = []
    for s in scored_articles:
        p = s.paper
        results.append({
            "pmid": p.pmid,
            "title": p.title,
            "title_ja": p.title_ja,
            "abstract": p.abstract,
            "summary_ja": p.summary_ja,
            "first_author": p.first_author,
            "authors": p.authors,
            "affiliation": p.affiliation,
            "journal": p.journal,
            "volume": p.volume,
            "issue": p.issue,
            "pub_date": p.pub_date,
            "doi": p.doi,
            "url": p.url,
            "journal_vol_issue": p.journal_vol_issue,
            "keywords": p.keywords,
            "mesh_terms": p.mesh_terms,
            "is_starred": s.is_starred,
            "interest_topics": s.interest_topics,
            "general_topics": s.general_topics,
            "all_topics": s.all_topics,
        })
    return results


def _save_weekly_json(
    scored_articles,
    weekly_comment: str,
    meta: dict,
) -> str:
    """Save weekly results to a JSON file. Returns the file path."""
    _ensure_data_dir()
    now = datetime.now()
    week = now.isocalendar()[1]
    filename = f"{now.year}-W{week:02d}.json"
    filepath = os.path.join(DATA_DIR, filename)

    payload = {
        "generated_at": now.isoformat(),
        "issue_label": f"Vol.{week} — {now.year}-W{week:02d}",
        "weekly_comment": weekly_comment,
        "meta": meta,
        "papers": _scored_to_dict(scored_articles),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return filepath


def execute_spine_pipeline(
    days: int = 7,
    max_papers: int = 10,
    post_to_notion: bool = True,
) -> dict:
    """Execute the spine weekly review pipeline.

    Selects up to ``max_papers`` papers total, prioritizing ★ interest-area
    papers first (by interest score), then filling remaining slots with the
    highest-scoring general papers.

    Results are always saved to ``data/spine/YYYY-WNN.json``.
    Notion posting is attempted via the Python SDK if NOTION_API_KEY is set;
    otherwise the JSON file can be picked up by Claude Code (MCP tools).

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include in the newsletter (default 10).
        post_to_notion: Whether to post to Notion.

    Returns:
        Summary dict.
    """
    start_time = datetime.now()
    logger.info(f"=== Spine pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    pubmed = SpinePubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しい脊椎関連論文は見つかりませんでした。"
        print(f"  {msg}")
        logger.info(msg)
        return {"papers_found": 0, "posted": False}

    total_found = len(papers)
    print(f"  → {total_found}件の論文を取得")

    # Step 2: Deduplicate using local PMID tracking
    print("🔄 過去の投稿と重複チェック中...")
    existing_pmids = _load_posted_pmids()
    duplicates_removed = 0
    if existing_pmids:
        papers, duplicates_removed = _deduplicate(papers, existing_pmids)
        if duplicates_removed > 0:
            print(f"  → {duplicates_removed}件を既出として除外（残り: {len(papers)}件）")
        else:
            print(f"  → 重複なし（{len(papers)}件すべて新規）")
    else:
        print(f"  → 初回実行（{len(papers)}件すべて新規）")

    # Handle all-duplicate case
    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。")
        return {
            "papers_found": total_found,
            "duplicates_removed": duplicates_removed,
            "papers_new": 0,
            "posted": False,
        }

    # Step 3: Score and classify
    print("📊 関連度スコアリング中...")
    from src.spine.scorer import SpineRelevanceScorer
    scorer = SpineRelevanceScorer()
    scored = scorer.score_and_rank(papers)
    top = scored[:max_papers]

    starred = [s for s in top if s.is_starred]
    non_starred = [s for s in top if not s.is_starred]

    # Step 4: Summarize with Claude API (optional)
    print("🤖 日本語要約・翻訳中（Claude API）...")
    weekly_comment = ""
    try:
        from src.spine.summarizer import SpineSummarizer
        summarizer = SpineSummarizer()
        all_papers_for_summary = [s.paper for s in top]
        summarizer.summarize_papers(all_papers_for_summary)
        weekly_comment = summarizer.generate_weekly_comment(
            all_papers_for_summary,
            starred_count=len(starred),
            total_count=len(top),
            total_before_curation=len(scored),
        )
        print("  ✓ 要約完了")
    except ValueError as e:
        logger.warning(f"Summarizer skipped: {e}")
        print(f"  ⚠ 要約スキップ（ANTHROPIC_API_KEY未設定）: {e}")
    except Exception as e:
        logger.warning(f"Summarizer failed: {e}")
        print(f"  ⚠ 要約エラー: {e}")

    # Step 5: Save results to JSON (always)
    meta = {
        "days": days,
        "total_found": total_found,
        "duplicates_removed": duplicates_removed,
        "total_scored": len(scored),
        "papers_included": len(top),
        "starred_count": len(starred),
    }
    json_path = _save_weekly_json(top, weekly_comment, meta)
    print(f"\n💾 結果を保存: {json_path}")

    # Display results
    print(f"\n{'='*60}")
    if starred:
        print(f"  ★ 関心領域: {len(starred)}件 / 関心領域外: {len(non_starred)}件")
    else:
        print(f"  📋 新規論文: {len(top)}件（関心領域該当なし）")
    print(f"  検索期間: 過去{days}日間 | 新規: {len(scored)}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    if starred:
        print("  ★ 関心領域の論文:")
        for rank, s in enumerate(starred, 1):
            p = s.paper
            topics = ", ".join(s.interest_topics)
            print(f"    ★#{rank} [{topics}]")
            print(f"       {p.title}")
            if p.title_ja:
                print(f"       → {p.title_ja}")
            print(f"       {p.first_author} | {p.journal_vol_issue}")
            print(f"       {p.url}")
            print()

    if non_starred:
        print("  関心領域外:")
        start = len(starred) + 1
        for rank, s in enumerate(non_starred, start):
            p = s.paper
            topics = ", ".join(s.general_topics) if s.general_topics else "General"
            print(f"    #{rank} [{topics}]")
            print(f"       {p.title}")
            print(f"       {p.first_author} | {p.journal_vol_issue}")
            print()

    # Step 6: Post to Notion via Python SDK (if NOTION_API_KEY is set)
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中...")
        try:
            from src.spine.notion_client import SpineNotionClient
            notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                top,
                weekly_comment=weekly_comment,
                days=days,
                total_before_dedup=total_found,
                duplicates_removed=duplicates_removed,
            )
            # Track posted PMIDs
            new_pmids = existing_pmids | {s.paper.pmid for s in top}
            _save_posted_pmids(new_pmids)
            print(f"  ✓ Notion投稿完了: {notion_url}")
        except ValueError:
            print(f"  ⚠ NOTION_API_KEY未設定 — JSONファイルからNotion MCP経由で投稿してください")
            print(f"     → {json_path}")
        except Exception as e:
            logger.error(f"Notion posting failed: {e}", exc_info=True)
            print(f"  ✗ Notion投稿失敗: {e}")
            print(f"     JSONファイルから再投稿可能: {json_path}")
    else:
        print("  (Notion投稿: スキップ)")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"=== Spine pipeline complete: {elapsed:.1f}s ===")

    return {
        "papers_found": total_found,
        "duplicates_removed": duplicates_removed,
        "papers_new": len(scored),
        "papers_included": len(top),
        "starred": len(starred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "json_path": json_path,
        "elapsed_seconds": elapsed,
    }
