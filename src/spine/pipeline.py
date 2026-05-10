"""Main pipeline: PubMed spine journal search → Dedup → Score → Notion post."""

import logging
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient
from src.spine.scorer import SpineRelevanceScorer

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
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    pubmed = SpinePubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しい脊椎論文は見つかりませんでした。"
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
    starred, unstarred = scorer.score_and_partition(papers)

    # Limit total
    all_scored = starred + unstarred
    if len(all_scored) > max_papers:
        # Keep all starred, trim unstarred
        remaining_slots = max(0, max_papers - len(starred))
        unstarred = unstarred[:remaining_slots]

    # Display results
    total_new = len(starred) + len(unstarred)
    print(f"\n{'='*60}")
    print(f"  📋 週刊スパイン — 今週のレポート")
    print(f"  検索期間: 過去{days}日間 | 新規: {total_new}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"  ★ 関心領域論文: {len(starred)}件 | その他: {len(unstarred)}件")
    print(f"{'='*60}\n")

    if starred:
        print("  ★ 関心領域論文:")
        for rank, s in enumerate(starred, 1):
            p = s.paper
            interests = ", ".join(s.matched_interests)
            print(f"    #{rank} [{interests}]")
            print(f"       {p.title}")
            print(f"       {p.first_author} | {p.journal} | {p.pub_date}")
            print()

    if unstarred:
        print("  その他の論文:")
        start_rank = len(starred) + 1
        for rank, s in enumerate(unstarred, start_rank):
            p = s.paper
            print(f"    #{rank} {p.title}")
            print(f"       {p.first_author} | {p.journal} | {p.pub_date}")
            print()

    # Step 4: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパイン）...")
        try:
            notion_url = notion.post_weekly_issue(
                starred, unstarred, days=days,
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
        "starred": len(starred),
        "unstarred": len(unstarred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
