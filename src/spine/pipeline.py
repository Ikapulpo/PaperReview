"""Main pipeline: PubMed search → Dedup → Scoring → Summarize → Notion post.

Searches 6 spine journals weekly and posts a newsletter to Notion.
"""

import logging
from datetime import datetime

from src.pubmed.client import PubMedClient

logger = logging.getLogger(__name__)

SPINE_JOURNAL_QUERY = (
    '"Spine"[Journal] OR "The spine journal"[Journal] OR '
    '"European spine journal"[Journal] OR '
    '"Journal of neurosurgery. Spine"[Journal] OR '
    '"Global spine journal"[Journal] OR '
    '("The Journal of bone and joint surgery. American volume"[Journal] AND '
    '(spine[Title] OR spinal[Title] OR vertebr*[Title] OR lumbar[Title] OR '
    'cervical[Title] OR thoracic[Title] OR scoliosis[Title] OR kyphosis[Title] OR '
    'disc[Title] OR intervertebral[Title] OR laminectomy[Title] OR fusion[Title]))'
)

SEARCH_BATCH_SIZE = 200


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

    # Step 1: Search PubMed
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎関連ジャーナル）...")
    pubmed = PubMedClient()
    papers = pubmed.search_and_fetch(
        days=days, query=SPINE_JOURNAL_QUERY, batch_size=SEARCH_BATCH_SIZE
    )

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
            logger.warning(f"Dedup skipped: {e}")
            print(f"  ⚠ 重複チェックスキップ: {e}")

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
    print("📊 関心領域スコアリング中...")
    from src.spine.scorer import SpineScorer
    scorer = SpineScorer()
    scored = scorer.score_all(papers)
    top = scored[:max_papers]

    starred = [s for s in top if s.is_starred]
    unstarred = [s for s in top if not s.is_starred]

    # Step 4: Summarize with Claude API
    print("🤖 タイトル翻訳・要約生成中...")
    try:
        from src.spine.summarizer import SpineSummarizer
        summarizer = SpineSummarizer()
        summaries = summarizer.summarize_papers([s.paper for s in top])
        for s in top:
            if s.paper.pmid in summaries:
                s.title_ja = summaries[s.paper.pmid].title_ja
                s.abstract_summary = summaries[s.paper.pmid].summary
        print(f"  → {len(summaries)}件の翻訳・要約完了")
    except ValueError as e:
        logger.warning(f"Summarization skipped: {e}")
        print(f"  ⚠ 翻訳・要約スキップ（ANTHROPIC_API_KEY未設定）: {e}")
        summarizer = None

    # Generate smart opening comment
    smart_comment = ""
    if summarizer:
        print("💬 導入コメント生成中...")
        try:
            starred_titles = [s.paper.title[:80] for s in starred]
            smart_comment = summarizer.generate_weekly_comment(
                [s.paper for s in top],
                star_count=len(starred),
                starred_titles=starred_titles,
            )
        except Exception as e:
            logger.warning(f"Comment generation failed: {e}")
    if not smart_comment:
        smart_comment = _fallback_comment(len(top), len(starred), duplicates_removed)

    # Display results
    print(f"\n{'='*60}")
    print(f"  🦴 週刊スパイン | 新規: {len(top)}件 | ★: {len(starred)}件")
    if duplicates_removed > 0:
        print(f"  検索期間: 過去{days}日間（既出{duplicates_removed}件除外）")
    else:
        print(f"  検索期間: 過去{days}日間")
    print(f"{'='*60}\n")

    if starred:
        print("  ── ★ 関心領域の論文 ──")
        for rank, s in enumerate(starred, 1):
            p = s.paper
            areas = ", ".join(s.interest_areas)
            print(f"  ★#{rank} [{areas}]")
            print(f"     {p.title}")
            if s.title_ja:
                print(f"     （{s.title_ja}）")
            print(f"     {p.first_author} et al. | {p.journal}")
            print(f"     {p.url}")
            print()

    if unstarred:
        print("  ── その他の論文 ──")
        offset = len(starred) + 1
        for rank, s in enumerate(unstarred[:10], offset):
            p = s.paper
            print(f"  #{rank} {p.title[:80]}")
            print(f"     {p.first_author} et al. | {p.journal}")
            print()
        if len(unstarred) > 10:
            print(f"  ... 他{len(unstarred) - 10}件\n")

    # Step 5: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパイン メルマガ）...")
        try:
            if notion is None:
                from src.spine.notion_client import SpineNotionClient
                notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                top,
                smart_comment=smart_comment,
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
        "papers_new": len(scored),
        "papers_included": len(top),
        "starred": len(starred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }


def _fallback_comment(total: int, starred: int, dedup: int) -> str:
    parts = [f"今週の脊椎関連ジャーナルから{total}件の新着論文をピックアップしました。"]
    if starred > 0:
        parts.append(f"関心領域に該当する論文が{starred}件あります。")
    if dedup > 0:
        parts.append(f"（既出{dedup}件は除外済み）")
    return "".join(parts)
