"""Claude API-based summarizer for spine papers.

Translates titles to Japanese and generates 3-5 line abstract summaries.
"""

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

from src.config import config
from src.pubmed.client import Paper

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = """\
あなたは脊椎外科領域の医学翻訳者です。
以下の学術論文について、各論文ごとに下記を日本語で出力してください。

1. title_ja: 論文タイトルの日本語訳（自然で正確な医学用語を使用）
2. summary: 要旨（Abstract）の内容を日本語で3〜5行に要約（箇条書きではなく文章で）

出力は下記のJSON形式のみで返してください。説明文は不要です。
```json
{
  "PMID": {"title_ja": "...", "summary": "..."},
  ...
}
```
"""

COMMENT_PROMPT = """\
あなたは脊椎外科の週刊メールマガジンの編集者です。
今週の論文リストを見て、読者（脊椎外科医・研究者）に向けた導入コメントを3〜4文で書いてください。

条件:
- 親しみやすく、少しウィットに富んだトーンで
- 今週の注目ポイントや傾向に触れる
- 関心領域（★付き）の論文があればそれにも言及する
- 「今週も週刊スパインをお届けします」的な定型文で始めない。変化をつけること

論文リスト:
{paper_list}

★関心領域の論文: {star_count}件
総論文数: {total_count}件
対象ジャーナル: Spine, The Spine Journal, European Spine Journal, JNS: Spine, Global Spine Journal, JBJS
"""


@dataclass
class PaperSummary:
    title_ja: str
    summary: str


class SpineSummarizer:

    MODEL = "claude-haiku-4-5-20251001"
    BATCH_SIZE = 25

    def __init__(self):
        api_key = config.anthropic_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for title translation and summarization. "
                "Set it in .env or as an environment variable."
            )
        self.client = Anthropic(api_key=api_key)

    def summarize_papers(self, papers: list[Paper]) -> dict[str, PaperSummary]:
        results: dict[str, PaperSummary] = {}
        for i in range(0, len(papers), self.BATCH_SIZE):
            batch = papers[i:i + self.BATCH_SIZE]
            batch_results = self._process_batch(batch)
            results.update(batch_results)
        logger.info(f"Summarized {len(results)}/{len(papers)} papers")
        return results

    def _process_batch(self, papers: list[Paper]) -> dict[str, PaperSummary]:
        paper_entries = []
        for p in papers:
            abstract_text = p.abstract[:1500] if p.abstract else "(abstract not available)"
            paper_entries.append(
                f"PMID: {p.pmid}\n"
                f"Title: {p.title}\n"
                f"Abstract: {abstract_text}\n"
            )

        user_msg = "\n---\n".join(paper_entries)

        try:
            resp = self.client.messages.create(
                model=self.MODEL,
                max_tokens=4096,
                system=TRANSLATE_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            return self._parse_response(resp.content[0].text)
        except Exception as e:
            logger.error(f"Summarization API call failed: {e}")
            return {p.pmid: PaperSummary(title_ja="", summary="") for p in papers}

    def _parse_response(self, text: str) -> dict[str, PaperSummary]:
        results: dict[str, PaperSummary] = {}
        try:
            cleaned = text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
                if cleaned.endswith("```"):
                    cleaned = cleaned[:-3]
            data = json.loads(cleaned)
            for pmid, info in data.items():
                results[str(pmid)] = PaperSummary(
                    title_ja=info.get("title_ja", ""),
                    summary=info.get("summary", ""),
                )
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"Failed to parse summarizer response: {e}")
        return results

    def generate_weekly_comment(
        self,
        papers: list[Paper],
        star_count: int,
        starred_titles: list[str],
    ) -> str:
        paper_lines = []
        for p in papers[:30]:
            paper_lines.append(f"- {p.title} ({p.journal})")

        if starred_titles:
            paper_lines.append(f"\n★付き論文: {', '.join(starred_titles[:5])}")

        paper_list = "\n".join(paper_lines)

        prompt = COMMENT_PROMPT.format(
            paper_list=paper_list,
            star_count=star_count,
            total_count=len(papers),
        )

        try:
            resp = self.client.messages.create(
                model=self.MODEL,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.error(f"Comment generation failed: {e}")
            return self._fallback_comment(len(papers), star_count)

    def _fallback_comment(self, total: int, starred: int) -> str:
        parts = [f"今週の脊椎関連ジャーナルから{total}件の新着論文をお届けします。"]
        if starred > 0:
            parts.append(f"関心領域に該当する論文が{starred}件ありました。")
        parts.append("ぜひチェックしてみてください。")
        return "".join(parts)
