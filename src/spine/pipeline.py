"""Main pipeline: PubMed search → Dedup → Scoring → Summarize → Notion post.

Weekly spine paper review for:
  Spine, The Spine Journal, European Spine Journal,
  JNS: Spine, Global Spine Journal, JBJS
"""

import logging
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient

logger = logging.getLogger(__name__)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(
    days: int = 7,
    max_papers: int = 50,
    post_to_notion: bool = True,
) -> dict:
    """Execute the spine weekly review pipeline.

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include in the newsletter.
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
                print(f"  → {duplicates_removed}件を既出として除外（残り: {len(papers)}件）")
            else:
                print(f"  → 重複なし（{len(papers)}件すべて新規）")
        except ValueError as e:
            logger.warning(f"Dedup skipped (Notion not configured): {e}")
            print(f"  ⚠ 重複チェックスキップ: {e}")

    # Handle all-duplicate case
    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。")
        if post_to_notion and notion:
            try:
                notion_url = notion.post_weekly_issue(
                    [], days=days,
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

    # Step 3: Score and classify
    print("📊 関連度スコアリング中...")
    from src.spine.scorer import SpineRelevanceScorer
    scorer = SpineRelevanceScorer()
    scored = scorer.score_and_rank(papers)
    top = scored[:max_papers]

    starred = [s for s in top if s.is_starred]
    non_starred = [s for s in top if not s.is_starred]

    # Step 4: Summarize with Claude API
    print("🤖 日本語要約・翻訳中（Claude API）...")
    weekly_comment = ""
    try:
        from src.spine.summarizer import SpineSummarizer
        summarizer = SpineSummarizer()

        # Translate titles and summarize abstracts
        all_papers_for_summary = [s.paper for s in top]
        summarizer.summarize_papers(all_papers_for_summary)

        # Generate weekly opening comment
        weekly_comment = summarizer.generate_weekly_comment(
            all_papers_for_summary,
            starred_count=len(starred),
            total_count=len(top),
        )
        print("  ✓ 要約完了")
    except ValueError as e:
        logger.warning(f"Summarizer skipped: {e}")
        print(f"  ⚠ 要約スキップ（ANTHROPIC_API_KEY未設定）: {e}")
    except Exception as e:
        logger.warning(f"Summarizer failed: {e}")
        print(f"  ⚠ 要約エラー: {e}")

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
        for rank, s in enumerate(non_starred[:10], start):
            p = s.paper
            topics = ", ".join(s.general_topics) if s.general_topics else "General"
            print(f"    #{rank} [{topics}]")
            print(f"       {p.title}")
            print(f"       {p.first_author} | {p.journal_vol_issue}")
            print()
        if len(non_starred) > 10:
            print(f"    ... 他{len(non_starred) - 10}件")
            print()

    # Step 5: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパイン）...")
        try:
            if notion is None:
                from src.spine.notion_client import SpineNotionClient
                notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                top,
                weekly_comment=weekly_comment,
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
        "papers_new": len(scored),
        "papers_included": len(top),
        "starred": len(starred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
