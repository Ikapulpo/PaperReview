"""Spine pipeline: PubMed journal search → Dedup → Scoring → Enrichment → Notion."""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient

logger = logging.getLogger(__name__)

SPINE_JOURNAL_QUERY = (
    '"Spine"[Journal] OR '
    '"Spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '"Journal of bone and joint surgery. American volume"[Journal]'
)


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
    logger.info(f"=== Spine pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed for spine journal papers
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    pubmed = PubMedClient()
    papers = pubmed.search_and_fetch(days=days, query=SPINE_JOURNAL_QUERY)

    if not papers:
        msg = "新しい脊椎ジャーナル論文は見つかりませんでした。"
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

    if not papers:
        print("\n📭 すべての論文が過去に取り上げ済みでした。")
        if post_to_notion and notion:
            try:
                from src.spine.enricher import SpineEnricher
                enricher = SpineEnricher()
                comment = enricher._fallback_comment([], duplicates_removed)
                notion_url = notion.post_weekly_issue(
                    [], weekly_comment=comment, days=days,
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

    # Step 3: Score and rank (★ interest areas + general topics)
    print("📊 関連度スコアリング中（★関心領域チェック）...")
    from src.spine.scorer import SpineScorer
    scorer = SpineScorer()
    scored = scorer.score_and_rank(papers)
    top = scored[:max_papers]

    star_count = sum(1 for s in top if s.is_star)
    print(f"  → ★関心領域: {star_count}件 / 関心領域外: {len(top) - star_count}件")

    # Step 4: Enrich with LLM (Japanese translation + summary)
    print("🌐 日本語タイトル・要約を生成中...")
    from src.spine.enricher import SpineEnricher
    enricher = SpineEnricher()
    enricher.enrich(top)
    if enricher.available:
        print("  → LLMによる翻訳・要約完了")
    else:
        print("  → フォールバック（ANTHROPIC_API_KEY未設定）")

    # Step 5: Generate weekly comment
    weekly_comment = enricher.generate_weekly_comment(top, duplicates_removed)

    # Display results
    print(f"\n{'='*60}")
    if star_count >= 3:
        print("  ⭐ 今週は関心領域の論文が豊富！")
    elif star_count >= 1:
        print("  ⭐ 今週は関心領域の論文あり")
    else:
        print("  📋 今週の脊椎ジャーナル論文をお届けします")
    print(f"  新規: {len(top)}件（★: {star_count}件）", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"{'='*60}\n")

    for rank, s in enumerate(top, 1):
        p = s.paper
        mark = "★ " if s.is_star else "  "
        topics = ", ".join(s.star_topics) if s.star_topics else ""
        print(f"  #{rank} {mark}[{topics}]" if topics else f"  #{rank} {mark}")
        print(f"     {p.title}")
        if s.title_ja:
            print(f"     （{s.title_ja}）")
        print(f"     {p.first_author} | {p.journal}")
        print()

    # Step 6: Post to Notion
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
        "star_count": star_count,
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
