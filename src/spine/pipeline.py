"""Main pipeline for 週刊スパイン: PubMed search → Dedup → Scoring → Notion post."""

import logging
from datetime import datetime

from src.spine.search import SpineSearchClient
from src.spine.scorer import SpineScorer

logger = logging.getLogger(__name__)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(days: int = 7, max_papers: int = 30, post_to_notion: bool = True) -> dict:
    """Execute the weekly spine review pipeline.

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include in the newsletter.
        post_to_notion: Whether to post to Notion.

    Returns:
        Summary dict.
    """
    start_time = datetime.now()
    logger.info(f"=== Spine Pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed for spine journals
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    client = SpineSearchClient()
    papers = client.search_and_fetch(days=days)

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

    # Step 3: Score and rank
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

    print("📊 関心領域スコアリング中...")
    scorer = SpineScorer()
    scored = scorer.score_and_rank(papers)
    top = scored[:max_papers]

    interest_papers = [s for s in top if s.is_interest]
    other_papers = [s for s in top if not s.is_interest]

    # Step 3b: AI summarization (title translation + abstract summary)
    summaries = {}
    try:
        from src.spine.summarizer import batch_summarize
        print("🤖 AI要約生成中（タイトル日本語訳 + 要旨要約）...")
        all_papers_for_summary = [s.paper for s in top]
        summaries = batch_summarize(all_papers_for_summary)
        if summaries:
            print(f"  → {len(summaries)}件の要約を生成")
        else:
            print("  → AI要約スキップ（ANTHROPIC_API_KEY未設定 or anthropicパッケージ未インストール）")
    except Exception as e:
        logger.warning(f"AI summarization failed: {e}")
        print(f"  ⚠ AI要約失敗: {e}")

    # Display results
    print(f"\n{'='*60}")
    if len(interest_papers) >= 5:
        print("  🎯 今週は豊作！ 関心領域ヒット多数")
    elif len(interest_papers) >= 1:
        print("  ⭐ 今週は★付き論文あり — チェック推奨")
    elif len(top) <= 5:
        print("  📭 今週は少なめ")
    else:
        print("  📋 今週の脊椎ジャーナル論文をお届けします")
    print(
        f"  検索期間: 過去{days}日間 | "
        f"新規: {len(scored)}件 | ★関心領域: {len(interest_papers)}件",
        end=""
    )
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    if interest_papers:
        print("  ★ 関心領域 ★")
        for rank, s in enumerate(interest_papers, 1):
            p = s.paper
            topics = ", ".join(s.interest_topics)
            print(f"  ★#{rank} [{topics}]")
            print(f"     {p.title}")
            print(f"     {p.first_author} et al. | {p.journal}")
            print()

    if other_papers:
        print("  ── 関心領域外 ──")
        for rank, s in enumerate(other_papers, 1):
            p = s.paper
            topics = ", ".join(s.general_topics[:2]) if s.general_topics else "General"
            print(f"  #{rank} [{topics}]")
            print(f"     {p.title}")
            print(f"     {p.first_author} et al. | {p.journal}")
            print()

    # Step 4: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパインメルマガ）...")
        try:
            if notion is None:
                from src.spine.notion_client import SpineNotionClient
                notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                top, days=days,
                total_before_dedup=total_found,
                duplicates_removed=duplicates_removed,
                summaries=summaries,
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
        "papers_new": len(scored),
        "papers_included": len(top),
        "interest_count": len(interest_papers),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
