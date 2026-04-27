"""Main pipeline: PubMed search → Dedup → Scoring → Notion newsletter post."""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient
from src.scorer.relevance import RelevanceScorer

logger = logging.getLogger(__name__)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    """Remove papers whose PMIDs are already in Notion."""
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_pipeline(days: int = 7, max_papers: int = 20, post_to_notion: bool = True) -> dict:
    """Execute the full weekly review pipeline."""
    start_time = datetime.now()
    logger.info(f"=== Pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed
    print(f"🔍 PubMed検索中（過去{days}日間のNKT細胞論文）...")
    pubmed = PubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しいNKT細胞論文は見つかりませんでした。"
        print(f"  {msg}")
        logger.info(msg)
        return {"papers_found": 0, "posted": False}

    total_found = len(papers)
    print(f"  → {total_found}件の論文を取得")

    # Step 2: Deduplicate against existing Notion entries
    duplicates_removed = 0
    notion = None
    if post_to_notion:
        print("🔄 過去の投稿と重複チェック中...")
        try:
            from src.notion.client import NotionClient
            notion = NotionClient()
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
        print("\n📭 すべての論文が過去に取り上げ済みでした。新規論文はありません。")
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

    print("📊 関連度スコアリング中（トピック・手法・研究領域）...")
    scorer = RelevanceScorer()
    scored = scorer.score_and_rank(papers)
    top = scored[:max_papers]

    # Display results
    top_score = top[0].total_score if top else 0

    print(f"\n{'='*64}")
    if top_score >= 0.6:
        print("  🎯 今週は当たり週！ 研究に直結しそうな論文あり")
    elif top_score >= 0.3:
        print("  ⭐ 今週は注目論文あり — チェック推奨")
    elif top_score >= 0.15:
        print("  📝 今週はそこそこ関連論文あり")
    elif len(top) <= 2:
        print("  📭 今週は少なめ — 次週に期待")
    else:
        print("  📋 今週のNKT論文をお届けします")
    print(f"  検索期間: 過去{days}日間 | 新規: {len(scored)}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*64}\n")

    for rank, s in enumerate(top, 1):
        p = s.paper
        topics = ", ".join(s.matched_topics) if s.matched_topics else "General"

        print(f"  #{rank} [スコア: {s.total_score:.2f}] [{topics}]")
        print(f"     {p.title}")
        print(f"     {p.first_author} et al. | {p.journal} | {p.pub_date}")
        print(f"     {p.url}")

        # Show research area connections
        if s.matched_areas:
            areas_str = ", ".join(
                f"{a} ({s.research_area_scores[a]:.2f})" for a in s.matched_areas
            )
            print(f"     📌 研究領域: {areas_str}")

        # Show detected methods
        if s.matched_methods:
            print(f"     🔬 手法: {', '.join(s.matched_methods)}")

        # Show recommendation reason (first line only for console)
        if s.recommendation_reason:
            first_line = s.recommendation_reason.split("\n")[0]
            print(f"     💡 {first_line}")

        print()

    # Step 4: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊NKT）...")
        try:
            if notion is None:
                from src.notion.client import NotionClient
                notion = NotionClient()
            notion_url = notion.post_weekly_issue(
                top, days=days,
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
    logger.info(f"=== Pipeline complete: {elapsed:.1f}s ===")

    return {
        "papers_found": total_found,
        "duplicates_removed": duplicates_removed,
        "papers_new": len(scored),
        "papers_included": len(top),
        "top_score": top_score,
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
