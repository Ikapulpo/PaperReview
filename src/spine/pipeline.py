"""Main pipeline for 週刊スパイン: PubMed search → Dedup → Scoring → Notion post."""

import logging
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient
from src.spine.relevance import SpineRelevanceScorer

logger = logging.getLogger(__name__)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(days: int = 7, max_papers: int = 50, post_to_notion: bool = True) -> dict:
    """Execute the weekly spine review pipeline.

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include.
        post_to_notion: Whether to post to Notion.

    Returns:
        Summary dict.
    """
    start_time = datetime.now()
    logger.info(f"=== Spine Pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎関連論文）...")
    pubmed = SpinePubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しい脊椎関連論文は見つかりませんでした。"
        print(f"  {msg}")
        logger.info(msg)
        return {"papers_found": 0, "posted": False}

    total_found = len(papers)
    print(f"  → {total_found}件の論文を取得")

    # Step 2: Deduplicate
    duplicates_removed = 0
    if post_to_notion:
        print("🔄 過去の投稿と重複チェック中...")
        try:
            from src.spine.notion_client import SpineNotionClient
            notion = SpineNotionClient()
            existing_pmids = notion.get_existing_pmids()
            papers, duplicates_removed = _deduplicate(papers, existing_pmids)
            if duplicates_removed > 0:
                print(f"  → {duplicates_removed}件を既出として除外（残り: {len(papers)}件）")
            else:
                print(f"  → 重複なし（{len(papers)}件すべて新規）")
        except ValueError as e:
            logger.warning(f"Dedup skipped (Notion not configured): {e}")
            print(f"  ⚠ 重複チェックスキップ: {e}")

    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。")
        if post_to_notion:
            try:
                notion_url = notion.post_weekly_issue(
                    [], [], days=days,
                    total_before_dedup=total_found,
                    duplicates_removed=duplicates_removed,
                )
                print(f"  ✓ Notion投稿完了（新規なし）: {notion_url}")
            except Exception as e:
                print(f"  ✗ Notion投稿失敗: {e}")
        return {
            "papers_found": total_found,
            "duplicates_removed": duplicates_removed,
            "papers_new": 0,
            "posted": True,
        }

    # Step 3: Score and partition
    print("📊 関心領域スコアリング中...")
    scorer = SpineRelevanceScorer()
    interest_papers, other_papers = scorer.score_and_partition(papers)

    # Limit total papers
    if len(interest_papers) + len(other_papers) > max_papers:
        remaining_slots = max(0, max_papers - len(interest_papers))
        other_papers = other_papers[:remaining_slots]

    # Display results
    total_new = len(interest_papers) + len(other_papers)
    print(f"\n{'='*60}")
    if interest_papers:
        print(f"  ★ 関心領域: {len(interest_papers)}件")
    print(f"  📋 関心領域外: {len(other_papers)}件")
    print(f"  検索期間: 過去{days}日間 | 新規合計: {total_new}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    if interest_papers:
        print("  ★ 関心領域の論文:")
        for rank, s in enumerate(interest_papers, 1):
            p = s.paper
            topics = ", ".join(s.matched_interests)
            print(f"    #{rank} [{topics}]")
            print(f"       {p.title}")
            print(f"       {p.first_author} | {p.journal}")
            print()

    # Step 4: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパイン）...")
        try:
            notion_url = notion.post_weekly_issue(
                interest_papers, other_papers,
                days=days,
                total_before_dedup=total_found,
                duplicates_removed=duplicates_removed,
            )
            print(f"  ✓ Notion投稿完了: {notion_url}")
        except ValueError as e:
            logger.warning(f"Notion posting skipped: {e}")
            print(f"  ⚠ Notion投稿スキップ: {e}")
        except Exception as e:
            logger.error(f"Notion posting failed: {e}", exc_info=True)
            print(f"  ✗ Notion投稿失敗: {e}")
    else:
        print("  (Notion投稿: スキップ)")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"=== Spine Pipeline complete: {elapsed:.1f}s ===")

    return {
        "papers_found": total_found,
        "duplicates_removed": duplicates_removed,
        "papers_new": total_new,
        "interest_count": len(interest_papers),
        "other_count": len(other_papers),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
