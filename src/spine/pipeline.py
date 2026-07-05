"""Spine pipeline: PubMed search → Dedup → Scoring → Notion post."""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient
from src.spine.scorer import SpineScorer

logger = logging.getLogger(__name__)

SPINE_JOURNAL_QUERY = (
    '"Spine"[Journal] OR '
    '"The spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '"The Journal of bone and joint surgery. American volume"[Journal]'
)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(
    days: int = 7, max_papers: int = 30, post_to_notion: bool = True
) -> dict:
    start_time = datetime.now()
    logger.info(f"=== Spine pipeline start: {start_time.isoformat()} ===")

    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    pubmed = PubMedClient()
    papers = pubmed.search_and_fetch(days=days, query=SPINE_JOURNAL_QUERY)

    if not papers:
        msg = "新しい脊椎関連論文は見つかりませんでした。"
        print(f"  {msg}")
        logger.info(msg)
        return {"papers_found": 0, "posted": False}

    total_found = len(papers)
    print(f"  → {total_found}件の論文を取得")

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
            logger.warning(f"Dedup skipped: {e}")
            print(f"  ⚠ 重複チェックスキップ: {e}")

    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。")
        if post_to_notion:
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

    starred = [s for s in top if s.is_starred]
    unstarred = [s for s in top if not s.is_starred]

    print(f"\n{'='*60}")
    if starred:
        print(f"  ★ 関心領域ヒット: {len(starred)}件")
    else:
        print("  📋 関心領域へのヒットなし")
    print(f"  検索期間: 過去{days}日間 | 新規: {len(scored)}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    if starred:
        print("  ── ★ 関心領域 ──")
        for rank, s in enumerate(starred, 1):
            p = s.paper
            areas = ", ".join(s.interest_areas)
            print(f"  ★#{rank} [{areas}]")
            print(f"     {p.title}")
            print(f"     {p.first_author} et al. | {p.journal}")
            print(f"     {p.url}")
            print()

    if unstarred:
        print("  ── 📋 関心領域外 ──")
        for rank, s in enumerate(unstarred, 1):
            p = s.paper
            topics = ", ".join(s.general_topics) if s.general_topics else "General"
            print(f"  #{rank} [{topics}]")
            print(f"     {p.title}")
            print(f"     {p.first_author} et al. | {p.journal}")
            print(f"     {p.url}")
            print()

    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパインメルマガ）...")
        try:
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
