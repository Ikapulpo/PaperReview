"""CLI interface for the paper review system (NKT + Spine)."""

import argparse
import logging
import sys


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ── NKT commands ──────────────────────────────────────────────────────

def cmd_run(args):
    """Run the NKT paper review pipeline once."""
    from src.pipeline import execute_pipeline
    result = execute_pipeline(
        days=args.days,
        max_papers=args.max_papers,
        post_to_notion=not args.no_notion,
    )
    if result["papers_found"] == 0:
        print("\n論文が見つかりませんでした。検索期間を広げてみてください (--days)")


def cmd_search(args):
    """Search PubMed only (no Notion posting)."""
    from src.pipeline import execute_pipeline
    execute_pipeline(
        days=args.days,
        max_papers=args.max_papers,
        post_to_notion=False,
    )


# ── Spine commands ────────────────────────────────────────────────────

def cmd_spine_run(args):
    """Run the spine paper review pipeline once."""
    from src.spine.pipeline import execute_spine_pipeline
    result = execute_spine_pipeline(
        days=args.days,
        max_papers=args.max_papers,
        post_to_notion=not args.no_notion,
    )
    if result["papers_found"] == 0:
        print("\n論文が見つかりませんでした。検索期間を広げてみてください (--days)")


def cmd_spine_search(args):
    """Search PubMed for spine papers only (no Notion posting)."""
    from src.spine.pipeline import execute_spine_pipeline
    execute_spine_pipeline(
        days=args.days,
        max_papers=args.max_papers,
        post_to_notion=False,
    )


def cmd_spine_verify(args):
    """Verify Spine Notion integration."""
    from src.spine.notion_client import SpineNotionClient
    try:
        client = SpineNotionClient()
        if client.verify_connection():
            print("✓ Spine Notion接続成功")
        else:
            print("✗ Spine Notion接続失敗")
            sys.exit(1)
    except ValueError as e:
        print(f"✗ 設定エラー: {e}")
        sys.exit(1)


# ── Shared commands ───────────────────────────────────────────────────

def cmd_schedule(args):
    """Start the weekly scheduler (NKT + Spine)."""
    from src.scheduler.runner import start_scheduler
    try:
        start_scheduler()
    except KeyboardInterrupt:
        print("\nスケジューラを停止しました。")


def cmd_verify(args):
    """Verify NKT Notion integration."""
    from src.notion.client import NotionClient
    try:
        client = NotionClient()
        if client.verify_connection():
            print("✓ NKT Notion接続成功")
        else:
            print("✗ NKT Notion接続失敗")
            sys.exit(1)
    except ValueError as e:
        print(f"✗ 設定エラー: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="論文自動レビューシステム（週刊NKT + 週刊スパイン）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
使用例:
  paper-review run                  NKT論文レビューを実行
  paper-review spine run            脊椎論文レビューを実行
  paper-review spine run --days 14  過去14日間の脊椎論文を検索
  paper-review spine search         脊椎PubMed検索のみ (Notion投稿なし)
  paper-review schedule             毎週自動実行スケジューラを起動 (NKT+Spine)
  paper-review verify               NKT Notion接続テスト
  paper-review spine verify         Spine Notion接続テスト
""",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ出力")

    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # run (NKT)
    p_run = subparsers.add_parser("run", help="NKT論文レビューを実行")
    p_run.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_run.add_argument("--max-papers", type=int, default=20, help="最大表示論文数 (デフォルト: 20)")
    p_run.add_argument("--no-notion", action="store_true", help="Notion投稿をスキップ")
    p_run.set_defaults(func=cmd_run)

    # search (NKT)
    p_search = subparsers.add_parser("search", help="NKT PubMed検索のみ")
    p_search.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_search.add_argument("--max-papers", type=int, default=20, help="最大表示論文数 (デフォルト: 20)")
    p_search.set_defaults(func=cmd_search)

    # spine (subcommand group)
    p_spine = subparsers.add_parser("spine", help="脊椎論文レビュー")
    spine_sub = p_spine.add_subparsers(dest="spine_command", help="Spineコマンド")

    # spine run
    p_spine_run = spine_sub.add_parser("run", help="脊椎論文レビューを実行")
    p_spine_run.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_spine_run.add_argument("--max-papers", type=int, default=50, help="最大表示論文数 (デフォルト: 50)")
    p_spine_run.add_argument("--no-notion", action="store_true", help="Notion投稿をスキップ")
    p_spine_run.set_defaults(func=cmd_spine_run)

    # spine search
    p_spine_search = spine_sub.add_parser("search", help="脊椎PubMed検索のみ")
    p_spine_search.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_spine_search.add_argument("--max-papers", type=int, default=50, help="最大表示論文数 (デフォルト: 50)")
    p_spine_search.set_defaults(func=cmd_spine_search)

    # spine verify
    p_spine_verify = spine_sub.add_parser("verify", help="Spine Notion接続テスト")
    p_spine_verify.set_defaults(func=cmd_spine_verify)

    # schedule (both)
    p_schedule = subparsers.add_parser("schedule", help="スケジューラ起動 (NKT+Spine)")
    p_schedule.set_defaults(func=cmd_schedule)

    # verify (NKT)
    p_verify = subparsers.add_parser("verify", help="NKT Notion接続テスト")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "spine" and not getattr(args, "spine_command", None):
        p_spine.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
