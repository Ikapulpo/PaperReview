#!/usr/bin/env python3
"""Spine weekly search: PubMed検索 + スコアリング → JSON出力.

Claude Code routine から呼び出され、結果をJSON形式で標準出力に出す。
Notion投稿はClaude Code側でMCPツールを使って行う。
"""

import json
import sys
from datetime import datetime, timedelta

from src.spine.pubmed_client import SpinePubMedClient
from src.spine.scorer import SpineScorer


def run(days: int = 7) -> dict:
    pubmed = SpinePubMedClient()
    papers = pubmed.search_and_fetch(days=days)

    if not papers:
        return {"papers": [], "meta": {"total": 0, "starred": 0, "date_range": _date_range(days)}}

    scorer = SpineScorer()
    scored = scorer.score_and_classify(papers)

    results = []
    for s in scored:
        p = s.paper
        results.append({
            "pmid": p.pmid,
            "title": p.title,
            "abstract": p.abstract[:800],
            "first_author": p.first_author,
            "affiliation": p.affiliation[:200],
            "journal": p.journal,
            "volume": p.volume,
            "issue": p.issue,
            "journal_vol_issue": p.journal_vol_issue,
            "pub_date": p.pub_date,
            "doi": p.doi,
            "url": p.url,
            "is_starred": s.is_starred,
            "interest_areas": s.interest_areas,
            "general_topics": s.general_topics,
            "all_topics": s.all_topics,
        })

    starred = [r for r in results if r["is_starred"]]
    meta = {
        "total": len(results),
        "starred": len(starred),
        "unstarred": len(results) - len(starred),
        "date_range": _date_range(days),
        "week_monday": _week_monday(),
        "issue_label": _issue_label(),
        "journals": sorted(set(r["journal"] for r in results)),
    }

    return {"papers": results, "meta": meta}


def _date_range(days: int) -> str:
    end = datetime.now()
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"


def _week_monday() -> str:
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _issue_label() -> str:
    now = datetime.now()
    week_num = now.isocalendar()[1]
    return f"Vol.{week_num} — {now.year}-W{week_num:02d}"


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    result = run(days=days)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
