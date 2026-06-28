"""Pipeline for weekly spine paper search, scoring, and JSON output.

Usage:
    python -m src.spine.pipeline                    # default 7 days
    python -m src.spine.pipeline --days 10          # custom lookback
    python -m src.spine.pipeline --max-papers 30    # custom limit
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

from src.spine.search import SpineSearchClient
from src.spine.scorer import SpineScorer

logger = logging.getLogger(__name__)


def run_pipeline(days: int = 7, max_papers: int = 50) -> dict:
    """Search PubMed, score papers, and return structured results.

    Returns a dict with metadata and a list of scored papers (★ first).
    """
    start = datetime.now()
    client = SpineSearchClient()
    papers = client.search_and_fetch(days=days)

    if not papers:
        return {
            "search_date": start.isoformat(),
            "days": days,
            "total_found": 0,
            "papers": [],
        }

    scorer = SpineScorer()
    scored = scorer.score_and_sort(papers)

    if max_papers and len(scored) > max_papers:
        scored = scored[:max_papers]

    starred_count = sum(1 for s in scored if s.is_starred)

    return {
        "search_date": start.isoformat(),
        "days": days,
        "total_found": len(papers),
        "included": len(scored),
        "starred_count": starred_count,
        "week_label": _week_label(),
        "date_range": _date_range(days),
        "papers": [s.to_dict() for s in scored],
    }


def _week_label() -> str:
    now = datetime.now()
    week_num = now.isocalendar()[1]
    return f"Vol.{week_num} — {now.year}-W{week_num:02d}"


def _date_range(days: int) -> str:
    end = datetime.now()
    start = end - timedelta(days=days)
    return f"{start.strftime('%Y/%m/%d')} – {end.strftime('%Y/%m/%d')}"


def main():
    parser = argparse.ArgumentParser(description="Spine journal paper search pipeline")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default: 7)")
    parser.add_argument("--max-papers", type=int, default=50, help="Max papers (default: 50)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", stream=sys.stderr)

    result = run_pipeline(days=args.days, max_papers=args.max_papers)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stderr)
    print(
        f"Found {result['total_found']} papers, included {result.get('included', 0)} "
        f"({result.get('starred_count', 0)} starred)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
