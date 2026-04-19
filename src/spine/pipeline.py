"""Main pipeline for spine weekly review:
PubMed search → Dedup → Spine filter → Score → Summarize → Notion post.
"""

import logging
import re
from datetime import datetime

from src.spine.pubmed import SpinePubMedClient
from src.spine.scorer import SpineInterestScorer

logger = logging.getLogger(__name__)

SPINE_SPECIFIC_JOURNALS = {
    "spine", "the spine journal", "european spine journal",
    "journal of neurosurgery. spine", "global spine journal",
}

SPINE_RELEVANCE_TERMS = [
    "spine", "spinal", "vertebr", "lumbar", "cervical", "thoracic",
    "thoracolumbar", "lumbosacral", "cervicothoracic",
    "disc", "intervertebral", "interbody",
    "scoliosis", "kyphosis", "lordosis", "spondylol",
    "laminectomy", "laminoplasty", "discectomy", "foraminotomy",
    "pedicle screw", "spinal fusion", "spinal cord",
    "stenosis", "myelopathy", "radiculopathy", "cauda equina",
    "sacral", "sacroiliac", "coccyx", "sacrum",
    "paraplegia", "quadriplegia", "tetraplegia",
]


def _is_spine_relevant(paper) -> bool:
    """Check if a paper from a general journal is spine-related."""
    journal_lower = paper.journal.lower()
    for name in SPINE_SPECIFIC_JOURNALS:
        if name in journal_lower:
            return True
    text = f"{paper.title} {paper.abstract}".lower()
    return any(term in text for term in SPINE_RELEVANCE_TERMS)


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

    # Filter JBJS and other general journals for spine relevance
    before_filter = len(papers)
    papers = [p for p in papers if _is_spine_relevant(p)]
    filtered_out = before_filter - len(papers)
    if filtered_out > 0:
        print(f"  → 脊椎関連フィルタ: {filtered_out}件を除外（残り: {len(papers)}件）")
        total_found = len(papers)

    # Step 2: Deduplicate
    duplicates_removed = 0
    notion = None
    if post_to_notion:
        print("🔄 過去の投稿と重複チェック中...")
        try:
            from src.spine.notion import SpineNotionClient
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
        print("\n📭 すべての論文が過去に取り上げ済みでした。新規論文はありません。")
        if post_to_notion and notion:
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

    # Step 3: Score interest areas
    print("📊 関心領域スコアリング中...")
    scorer = SpineInterestScorer()
    scored = scorer.score_all(papers)
    starred, unstarred = scorer.partition(scored)

    # Limit total papers
    if len(starred) + len(unstarred) > max_papers:
        remaining_slots = max(0, max_papers - len(starred))
        unstarred = unstarred[:remaining_slots]

    # Step 4: AI summarization (title translation + abstract summary)
    all_scored = starred + unstarred
    print(f"🤖 タイトル日本語訳・要旨要約中（{len(all_scored)}件）...")
    try:
        from src.spine.summarizer import summarize_papers
        papers_data = [
            {"title": s.paper.title, "abstract": s.paper.abstract}
            for s in all_scored
        ]
        summaries = summarize_papers(papers_data)
        for s, summary in zip(all_scored, summaries):
            s.title_ja = summary.get("title_ja", "")
            s.summary_ja = summary.get("summary_ja", "")
        has_ja = any(s.title_ja for s in all_scored)
        if has_ja:
            print("  → AI要約完了")
        else:
            print("  → AI要約スキップ（ANTHROPIC_API_KEY未設定またはエラー）")
    except Exception as e:
        logger.warning(f"Summarization failed: {e}")
        print(f"  ⚠ AI要約スキップ: {e}")

    # Display results
    print(f"\n{'='*60}")
    print(f"  🦴 週刊スパイン — 新規{len(all_scored)}件", end="")
    if duplicates_removed > 0:
        print(f"（既出{duplicates_removed}件除外）")
    else:
        print()
    print(f"  ★ 関心領域: {len(starred)}件 | その他: {len(unstarred)}件")
    print(f"{'='*60}\n")

    if starred:
        print("  ── ★ 関心領域 ──")
        for i, s in enumerate(starred, 1):
            areas = ", ".join(s.interest_areas)
            print(f"  ★#{i} [{areas}]")
            print(f"     {s.paper.title}")
            if s.title_ja:
                print(f"     （{s.title_ja}）")
            print(f"     {s.paper.first_author} | {s.paper.journal} | {s.paper.pub_date}")
            print()

    if unstarred:
        print("  ── その他 ──")
        offset = len(starred)
        for i, s in enumerate(unstarred, 1):
            print(f"  #{offset + i} {s.paper.title}")
            print(f"     {s.paper.first_author} | {s.paper.journal}")
            print()

    # Step 5: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパインメルマガ）...")
        try:
            if notion is None:
                from src.spine.notion import SpineNotionClient
                notion = SpineNotionClient()
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
        "papers_new": len(all_scored),
        "starred": len(starred),
        "unstarred": len(unstarred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
