"""CLI interface for the NKT paper review system."""

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


def cmd_run(args):
    """Run the paper review pipeline once."""
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


def cmd_schedule(args):
    """Start the weekly scheduler."""
    from src.scheduler.runner import start_scheduler
    try:
        start_scheduler()
    except KeyboardInterrupt:
        print("\nスケジューラを停止しました。")


def cmd_verify(args):
    """Verify Notion integration."""
    from src.notion.client import NotionClient
    try:
        client = NotionClient()
        if client.verify_connection():
            print("✓ Notion接続成功")
        else:
            print("✗ Notion接続失敗")
            sys.exit(1)
    except ValueError as e:
        print(f"✗ 設定エラー: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="週刊NKT - NKT細胞論文の自動レビューシステム",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
使用例:
  paper-review run                  今すぐ実行 (PubMed検索 + Notion投稿)
  paper-review run --days 14        過去14日間の論文を検索
  paper-review run --no-notion      Notion投稿なしで検索のみ
  paper-review search               PubMed検索のみ (Notion投稿なし)
  paper-review schedule             毎週自動実行スケジューラを起動
  paper-review verify               Notion接続テスト
""",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログ出力")

    subparsers = parser.add_subparsers(dest="command", help="コマンド")

    # run
    p_run = subparsers.add_parser("run", help="論文レビューを実行")
    p_run.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_run.add_argument("--max-papers", type=int, default=20, help="最大表示論文数 (デフォルト: 20)")
    p_run.add_argument("--no-notion", action="store_true", help="Notion投稿をスキップ")
    p_run.set_defaults(func=cmd_run)

    # search
    p_search = subparsers.add_parser("search", help="PubMed検索のみ")
    p_search.add_argument("--days", type=int, default=7, help="検索日数 (デフォルト: 7)")
    p_search.add_argument("--max-papers", type=int, default=20, help="最大表示論文数 (デフォルト: 20)")
    p_search.set_defaults(func=cmd_search)

    # schedule
    p_schedule = subparsers.add_parser("schedule", help="スケジューラ起動")
    p_schedule.set_defaults(func=cmd_schedule)

    # verify
    p_verify = subparsers.add_parser("verify", help="Notion接続テスト")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
