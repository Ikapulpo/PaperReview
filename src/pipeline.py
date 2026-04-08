"""Main pipeline: PubMed search → Scoring → Notion post."""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient
from src.scorer.relevance import RelevanceScorer

logger = logging.getLogger(__name__)


def execute_pipeline(days: int = 7, max_papers: int = 20, post_to_notion: bool = True) -> dict:
    """Execute the full weekly review pipeline.

    Args:
        days: Number of days to look back for papers.
        max_papers: Maximum number of papers to include in Notion.
        post_to_notion: Whether to post results to Notion.

    Returns:
        Summary dict with results.
    """
    start_time = datetime.now()
    logger.info(f"=== Pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed
    print(f"🔍 PubMedを検索中 (過去{days}日間のNKT細胞論文)...")
    pubmed = PubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しいNKT細胞論文は見つかりませんでした。"
        print(f"  {msg}")
        logger.info(msg)
        return {"papers_found": 0, "posted": False}

    print(f"  → {len(papers)}件の論文を取得")

    # Step 2: Score and rank
    print("📊 関連度スコアリング中...")
    scorer = RelevanceScorer()
    scored = scorer.score_and_rank(papers)

    # Display top results
    print(f"\n{'='*60}")
    print(f"  週刊NKT論文レビュー ({datetime.now().strftime('%Y/%m/%d')})")
    print(f"  検索期間: 過去{days}日間 | 総論文数: {len(scored)}")
    print(f"{'='*60}\n")

    for rank, s in enumerate(scored[:max_papers], 1):
        p = s.paper
        print(f"  #{rank} [スコア: {s.total_score:.1f}]")
        print(f"     {p.title}")
        print(f"     {p.first_author} et al. | {p.journal} | {p.pub_date}")
        print(f"     {s.recommendation_reason}")
        print(f"     {p.url}")
        print()

    # Step 3: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中 (週刊NKT)...")
        try:
            from src.notion.client import NotionClient
            notion = NotionClient()
            notion_url = notion.post_weekly_review(scored, days=days, max_papers=max_papers)
            print(f"  ✓ Notion投稿完了: {notion_url}")
        except ValueError as e:
            logger.warning(f"Notion posting skipped: {e}")
            print(f"  ⚠ Notion投稿スキップ: {e}")
        except Exception as e:
            logger.error(f"Notion posting failed: {e}")
            print(f"  ✗ Notion投稿失敗: {e}")
    else:
        print("  (Notion投稿: スキップ)")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"=== Pipeline complete: {elapsed:.1f}s ===")

    return {
        "papers_found": len(papers),
        "top_score": scored[0].total_score if scored else 0,
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
