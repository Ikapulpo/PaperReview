"""Claude API-based summarizer for spine papers.

Provides:
  - Japanese translation of paper titles
  - 3-5 line summary of abstracts in Japanese
  - Witty weekly opening commentary
"""

import logging

import anthropic

from src.config import config
from src.spine.pubmed_client import SpinePaper

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 10


class SpineSummarizer:
    """Translates and summarizes spine papers using Claude API."""

    def __init__(self):
        api_key = config.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for spine paper summarization. "
                "Set it in .env or as an environment variable."
            )
        self.client = anthropic.Anthropic(api_key=api_key)

    def summarize_papers(self, papers: list[SpinePaper]) -> list[SpinePaper]:
        """Add Japanese title translation and abstract summary to papers."""
        if not papers:
            return papers

        for i in range(0, len(papers), BATCH_SIZE):
            batch = papers[i:i + BATCH_SIZE]
            self._summarize_batch(batch)

        return papers

    def _summarize_batch(self, papers: list[SpinePaper]) -> None:
        """Summarize a batch of papers in a single API call."""
        paper_entries = []
        for idx, p in enumerate(papers):
            abstract_snippet = p.abstract[:1500] if p.abstract else "(抄録なし)"
            paper_entries.append(
                f"[{idx}]\nTitle: {p.title}\nAbstract: {abstract_snippet}"
            )

        prompt = (
            "あなたは脊椎外科領域の学術論文レビューアシスタントです。\n"
            "以下の論文について、それぞれ次の2つを出力してください:\n"
            "1. タイトルの日本語訳（簡潔・正確に）\n"
            "2. 抄録の要約（日本語で3〜5行、臨床的意義がわかるように）\n\n"
            "出力形式（番号で区切る）:\n"
            "[番号]\n日本語タイトル: ...\n要約: ...\n\n"
            "---\n\n"
            + "\n\n".join(paper_entries)
        )

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            self._parse_batch_response(response.content[0].text, papers)
        except anthropic.APIError as e:
            logger.warning(f"Claude API error during summarization: {e}")
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")

    def _parse_batch_response(self, text: str, papers: list[SpinePaper]) -> None:
        """Parse the batch response and assign to papers."""
        sections = text.split("[")
        for section in sections:
            if not section.strip():
                continue
            try:
                idx_str = section.split("]")[0].strip()
                idx = int(idx_str)
                if idx < 0 or idx >= len(papers):
                    continue

                body = section.split("]", 1)[1] if "]" in section else ""

                # Extract Japanese title
                title_ja = ""
                for line in body.split("\n"):
                    if "日本語タイトル" in line and ":" in line:
                        title_ja = line.split(":", 1)[1].strip()
                        break
                if title_ja:
                    papers[idx].title_ja = title_ja

                # Extract summary
                summary_lines = []
                in_summary = False
                for line in body.split("\n"):
                    if "要約" in line and ":" in line:
                        first_part = line.split(":", 1)[1].strip()
                        if first_part:
                            summary_lines.append(first_part)
                        in_summary = True
                        continue
                    if in_summary:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("["):
                            summary_lines.append(stripped)
                        elif stripped.startswith("["):
                            break

                if summary_lines:
                    papers[idx].summary_ja = "\n".join(summary_lines)

            except (ValueError, IndexError):
                continue

    def generate_weekly_comment(
        self,
        papers: list[SpinePaper],
        starred_count: int,
        total_count: int,
    ) -> str:
        """Generate a witty, insightful weekly opening comment."""
        if not papers:
            return (
                "今週は対象ジャーナルからの新規論文はありませんでした。"
                "静かな一週間ですが、次号をお楽しみに。"
            )

        # Build a brief summary of this week's papers for Claude
        highlights = []
        for p in papers[:15]:
            star = "★" if hasattr(p, "_starred") else ""
            highlights.append(f"{star}{p.title} ({p.journal})")

        prompt = (
            "あなたは脊椎外科の週刊論文レビュー「週刊スパイン」の編集者です。\n"
            "今週の論文リストを見て、読者（脊椎外科医）に向けた冒頭コメントを"
            "2〜4文で書いてください。\n\n"
            "条件:\n"
            "- 気の利いた、読みたくなるような文体で\n"
            "- 今週の傾向やハイライトに軽く触れる\n"
            "- 堅すぎず、かといってカジュアルすぎず\n"
            "- 絵文字は使わない\n"
            f"- 今週の新規論文: {total_count}件"
        )
        if starred_count > 0:
            prompt += f"（うち関心領域: {starred_count}件）"
        prompt += "\n\n今週の論文タイトル:\n" + "\n".join(highlights)

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Weekly comment generation failed: {e}")
            if starred_count > 0:
                return (
                    f"今週は{total_count}件の論文をお届けします。"
                    f"うち{starred_count}件が関心領域に該当しています。"
                )
            return f"今週は{total_count}件の論文をお届けします。"
