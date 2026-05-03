"""Main pipeline: PubMed search → Dedup → Scoring → Translation → Notion post.

Weekly spine journal review pipeline.
"""

import logging
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient
from src.spine.scorer import SpineScorer
from src.spine.translator import translate_and_summarize

logger = logging.getLogger(__name__)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(
    days: int = 7, max_papers: int = 50, post_to_notion: bool = True
) -> dict:
    """Execute the weekly spine review pipeline.

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include per group.
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

    # Step 2: Deduplicate
    duplicates_removed = 0
    notion = None
    if post_to_notion:
        print("🔄 過去の投稿と重複チェック中...")
        try:
            from src.spine.notion_client import SpineNotionClient

            notion = SpineNotionClient()
            existing_pmids = notion.get_existing_pmids()
            papers, duplicates_removed = _deduplicate(papers, existing_pmids)
            if duplicates_removed > 0:
                print(
                    f"  → {duplicates_removed}件を既出として除外"
                    f"（残り: {len(papers)}件）"
                )
            else:
                print(f"  → 重複なし（{len(papers)}件すべて新規）")
        except ValueError as e:
            logger.warning(f"Dedup skipped (Notion not configured): {e}")
            print(f"  ⚠ 重複チェックスキップ: {e}")

    # Step 3: Handle all-duplicate case
    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。新規論文はありません。")
        if post_to_notion and notion:
            try:
                notion_url = notion.post_weekly_issue(
                    [],
                    [],
                    days=days,
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

    # Step 4: Translate titles and summarise abstracts
    print("🌐 タイトル翻訳・要旨要約中...")
    translate_and_summarize(papers)
    translated_count = sum(1 for p in papers if p.title_ja)
    if translated_count > 0:
        print(f"  → {translated_count}件のタイトルを日本語訳")
    else:
        print("  → 翻訳スキップ（ANTHROPIC_API_KEY未設定またはSDK未インストール）")

    # Step 5: Score and partition
    print("📊 関心領域スコアリング中...")
    scorer = SpineScorer()
    starred, unstarred = scorer.score_and_partition(papers)

    # Limit output
    starred = starred[:max_papers]
    unstarred = unstarred[:max_papers]
    total_scored = len(starred) + len(unstarred)

    # Display results
    print(f"\n{'='*60}")
    if starred:
        print(f"  ★ 関心領域の論文: {len(starred)}件")
        topics = set()
        for s in starred:
            topics.update(s.matched_topics)
        if topics:
            print(f"    ({', '.join(sorted(topics))})")
    else:
        print("  関心領域に該当する論文は今週ありませんでした")
    print(f"  全論文数: {total_scored}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    if starred:
        print("── ★ 関心領域の論文 ──")
        for rank, s in enumerate(starred, 1):
            p = s.paper
            topics_str = ", ".join(s.matched_topics)
            print(f"  ★#{rank} [{topics_str}]")
            print(f"     {p.title}")
            if p.title_ja:
                print(f"     （{p.title_ja}）")
            print(f"     {p.first_author} | {p.journal_vol_issue}")
            print()

    if unstarred:
        print("── 関心領域外の論文 ──")
        for rank, s in enumerate(unstarred, 1):
            p = s.paper
            print(f"  #{rank} {p.title}")
            print(f"     {p.first_author} | {p.journal_vol_issue}")
            print()

    # Step 6: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパインメルマガ）...")
        try:
            if notion is None:
                from src.spine.notion_client import SpineNotionClient

                notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                starred,
                unstarred,
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
    logger.info(f"=== Spine pipeline complete: {elapsed:.1f}s ===")

    return {
        "papers_found": total_found,
        "duplicates_removed": duplicates_removed,
        "papers_new": len(papers),
        "starred": len(starred),
        "unstarred": len(unstarred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
