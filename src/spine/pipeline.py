"""Spine pipeline: PubMed search → Dedup → Scoring → LLM → Notion post."""

import logging
from datetime import datetime

from src.spine.pubmed_client import SpinePubMedClient
from src.spine.scorer import SpineScorer

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
    """Execute the weekly spine review pipeline.

    Args:
        days: Number of days to look back.
        max_papers: Maximum papers to include.
        post_to_notion: Whether to post to Notion.

    Returns:
        Summary dict.
    """
    start_time = datetime.now()
    logger.info(f"=== Spine Pipeline start: {start_time.isoformat()} ===")

    # Step 1: Search PubMed (spine journals)
    print(f"🔍 PubMed検索中（過去{days}日間の脊椎ジャーナル論文）...")
    pubmed = SpinePubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        msg = "新しい脊椎論文は見つかりませんでした。"
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
                notion_url = notion.post_weekly_issue(
                    [], intro_comment="",
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

    # Step 3: Score and classify
    print("📊 関心領域スコアリング・トピック分類中...")
    scorer = SpineScorer()
    scored = scorer.score_and_classify(papers)
    top = scored[:max_papers]

    starred = [s for s in top if s.is_starred]
    unstarred = [s for s in top if not s.is_starred]

    # Step 4: LLM translation and summarization (optional)
    print("🌐 タイトル翻訳・要旨要約中...")
    try:
        from src.spine.llm import process_papers, generate_weekly_intro

        papers_data = [
            {"pmid": s.paper.pmid, "title": s.paper.title, "abstract": s.paper.abstract}
            for s in top
        ]
        translations = process_papers(papers_data)

        for s in top:
            info = translations.get(s.paper.pmid, {})
            s.title_ja = info.get("title_ja", "")
            s.summary_ja = info.get("summary_ja", "")

        if translations:
            print(f"  → {len(translations)}件の翻訳・要約完了")
        else:
            print("  → LLMスキップ（ANTHROPIC_API_KEY未設定 or パッケージ未導入）")

        journals = list({s.paper.journal for s in top})
        all_starred_areas = set()
        for s in starred:
            all_starred_areas.update(s.interest_areas)
        intro_comment = generate_weekly_intro(
            n_papers=len(top),
            n_starred=len(starred),
            starred_areas=sorted(all_starred_areas),
            journals=journals,
        )
    except ImportError:
        print("  → LLMモジュール未利用")
        intro_comment = ""
        if not intro_comment:
            from src.spine.llm import _template_intro
            journals = list({s.paper.journal for s in top})
            all_starred_areas = set()
            for s in starred:
                all_starred_areas.update(s.interest_areas)
            intro_comment = _template_intro(
                len(top), len(starred), sorted(all_starred_areas), journals,
            )

    # Display results
    print(f"\n{'='*60}")
    print(f"  🦴 週刊スパイン — {len(top)}件")
    print(f"  ★関心領域: {len(starred)}件 | 関心領域外: {len(unstarred)}件")
    print(f"  検索期間: 過去{days}日間", end="")
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
            title_disp = s.title_ja if s.title_ja else p.title
            print(f"  ★#{rank} [{areas}]")
            print(f"     {p.title}")
            if s.title_ja:
                print(f"     （{s.title_ja}）")
            print(f"     {p.first_author} | {p.journal_vol_issue}")
            print(f"     {p.url}")
            print()

    if unstarred:
        print("  ── 関心領域外 ──")
        start = len(starred) + 1
        for rank, s in enumerate(unstarred, start):
            p = s.paper
            topics = ", ".join(s.general_topics) if s.general_topics else "General"
            print(f"  #{rank} [{topics}]")
            print(f"     {p.title}")
            if s.title_ja:
                print(f"     （{s.title_ja}）")
            print(f"     {p.first_author} | {p.journal_vol_issue}")
            print()

    # Step 5: Post to Notion
    notion_url = ""
    if post_to_notion:
        print("📝 Notionに投稿中（週刊スパイン メルマガ）...")
        try:
            if notion is None:
                from src.spine.notion_client import SpineNotionClient
                notion = SpineNotionClient()
            notion_url = notion.post_weekly_issue(
                top, intro_comment=intro_comment,
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
        "unstarred": len(unstarred),
        "posted": bool(notion_url),
        "notion_url": notion_url,
        "elapsed_seconds": elapsed,
    }
