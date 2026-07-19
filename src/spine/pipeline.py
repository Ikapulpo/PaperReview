"""Spine pipeline: PubMed search -> Dedup -> Scoring -> Notion post."""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient
from src.spine.search_query import SPINE_SEARCH_QUERY
from src.spine.scorer import SpineScorer

logger = logging.getLogger(__name__)

EXCLUDED_ARTICLE_TYPES = {"Letter", "Editorial", "Comment"}


def _is_substantive(paper) -> bool:
    """Filter out letters, editorials, and papers without abstracts."""
    if not paper.abstract or paper.abstract == "[Abstract not available]":
        return False
    return True


def _is_spine_related(paper) -> bool:
    """Filter out non-spine JBJS papers."""
    text = (paper.title + " " + paper.abstract).lower()
    spine_terms = [
        "spine", "spinal", "vertebr", "lumbar", "cervical", "thoracic",
        "disc", "scoliosis", "kyphosis", "laminectomy", "laminoplasty",
        "fusion", "deformity", "myelopathy", "radiculopathy", "stenosis",
        "pedicle", "interbody", "sacr", "coccyx",
    ]
    return any(term in text for term in spine_terms)


def _deduplicate(papers, existing_pmids: set[str]) -> tuple[list, int]:
    new_papers = [p for p in papers if p.pmid not in existing_pmids]
    removed = len(papers) - len(new_papers)
    return new_papers, removed


def execute_spine_pipeline(
    days: int = 7,
    max_papers: int = 50,
    post_to_notion: bool = True,
) -> dict:
    start_time = datetime.now()
    logger.info(f"=== Spine Pipeline start: {start_time.isoformat()} ===")

    print(f"🔍 PubMed検索中（過去{days}日間の脊椎関連論文）...")
    pubmed = PubMedClient()
    pubmed_original_query = pubmed.__class__.__dict__.get("_original_query", None)

    pmids = pubmed.search_recent_custom(SPINE_SEARCH_QUERY, days=days)
    if not pmids:
        msg = "新しい脊椎関連論文は見つかりませんでした。"
        print(f"  {msg}")
        return {"papers_found": 0, "posted": False}

    papers = pubmed.fetch_details(pmids)
    total_found = len(papers)
    print(f"  → {total_found}件の論文を取得")

    # Filter to substantive, spine-related papers
    papers = [p for p in papers if _is_substantive(p) and _is_spine_related(p)]
    filtered_out = total_found - len(papers)
    if filtered_out > 0:
        print(f"  → {filtered_out}件を除外（Letter/Editorial/非脊椎）、残り{len(papers)}件")

    # Deduplicate
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
        return {
            "papers_found": total_found,
            "duplicates_removed": duplicates_removed,
            "papers_new": 0,
            "posted": False,
        }

    # Score and partition
    print("📊 関心領域スコアリング中...")
    scorer = SpineScorer()
    starred, unstarred = scorer.score_and_partition(papers)

    print(f"\n{'='*60}")
    print(f"  ★ 関心領域: {len(starred)}件 | 関心領域外: {len(unstarred)}件")
    if duplicates_removed > 0:
        print(f"  既出除外: {duplicates_removed}件")
    print(f"{'='*60}\n")

    for rank, s in enumerate(starred, 1):
        cats = ", ".join(s.star_categories)
        print(f"  ★#{rank} [{cats}] {s.paper.title[:70]}...")
        print(f"     {s.paper.first_author} et al. | {s.paper.journal}")
        print()

    for rank, s in enumerate(unstarred[:10], 1):
        print(f"  #{rank} {s.paper.title[:70]}...")
        print(f"     {s.paper.first_author} et al. | {s.paper.journal}")
        print()

    # Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパインメルマガ）...")
        try:
            notion_url = notion.post_weekly_issue(
                starred, unstarred,
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
        "papers_new": len(starred) + len(unstarred),
        "starred": len(starred),
        "unstarred": len(unstarred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
