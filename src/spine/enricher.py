"""LLM enrichment: Japanese title translation and abstract summarization."""

import json
import logging
import os
import re

from src.spine.scorer import SpineScoredArticle

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


class SpineEnricher:

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def enrich(
        self,
        scored_articles: list[SpineScoredArticle],
    ) -> None:
        if not self.available:
            logger.info("ANTHROPIC_API_KEY not set — using fallback enrichment")
            self._fallback_enrich(scored_articles)
            return

        for i in range(0, len(scored_articles), BATCH_SIZE):
            batch = scored_articles[i:i + BATCH_SIZE]
            self._enrich_batch(batch)

    def _enrich_batch(self, articles: list[SpineScoredArticle]) -> None:
        papers_text = []
        for idx, art in enumerate(articles):
            p = art.paper
            abstract_excerpt = p.abstract[:1500] if p.abstract else "(no abstract)"
            papers_text.append(
                f"[{idx}] PMID: {p.pmid}\n"
                f"Title: {p.title}\n"
                f"Abstract: {abstract_excerpt}"
            )

        prompt = (
            "以下の脊椎関連の英語論文について、各論文の:\n"
            "1. タイトルの日本語訳\n"
            "2. 要旨の日本語要約（3〜5行、臨床的・学術的意義がわかるように）\n"
            "を作成してください。\n\n"
            "JSON形式で返してください（マークダウンのコードブロックは不要）:\n"
            '{"papers": [\n'
            '  {"idx": 0, "title_ja": "...", "summary_ja": "..."},\n'
            "  ...\n"
            "]}\n\n"
            "論文一覧:\n\n" + "\n\n".join(papers_text)
        )

        try:
            client = self._get_client()
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            text = re.sub(r"^```json\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)

            for item in data.get("papers", []):
                idx = item.get("idx", -1)
                if 0 <= idx < len(articles):
                    articles[idx].title_ja = item.get("title_ja", "")
                    articles[idx].summary_ja = item.get("summary_ja", "")

        except Exception as e:
            logger.warning(f"LLM enrichment failed, using fallback: {e}")
            self._fallback_enrich(articles)

    def generate_weekly_comment(
        self,
        scored_articles: list[SpineScoredArticle],
        duplicates_removed: int,
    ) -> str:
        if not self.available or not scored_articles:
            return self._fallback_comment(scored_articles, duplicates_removed)

        star_papers = [a for a in scored_articles if a.is_star]
        summary_lines = []
        for a in scored_articles[:10]:
            mark = "★" if a.is_star else " "
            topics = ", ".join(a.star_topics) if a.star_topics else ""
            summary_lines.append(f"{mark} {a.paper.title[:80]} [{topics}]")

        prompt = (
            "あなたは脊椎外科の週刊論文レビューの編集者です。\n"
            "以下の今週の論文リストを踏まえ、読者（脊椎外科医）に向けた"
            "気の利いた冒頭コメントを日本語で3〜4文で書いてください。\n"
            "★は編集者の関心領域（AI、手術適応、基礎研究、バイオマテリアル）の論文です。\n"
            "トーンは親しみやすく、かつ専門的に。\n\n"
            f"今週の論文数: {len(scored_articles)}件（★: {len(star_papers)}件）\n"
        )
        if duplicates_removed > 0:
            prompt += f"既出除外: {duplicates_removed}件\n"
        prompt += "\n主な論文:\n" + "\n".join(summary_lines)

        try:
            client = self._get_client()
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Comment generation failed: {e}")
            return self._fallback_comment(scored_articles, duplicates_removed)

    def _fallback_enrich(self, articles: list[SpineScoredArticle]) -> None:
        for art in articles:
            art.title_ja = ""
            if art.paper.abstract:
                sentences = re.split(r'(?<=[.!?])\s+', art.paper.abstract)
                key_sentences = []
                for s in sentences:
                    s_lower = s.lower()
                    if any(kw in s_lower for kw in [
                        "objective", "purpose", "aim", "background",
                        "result", "finding", "conclusion",
                        "significant", "demonstrate", "showed",
                    ]):
                        key_sentences.append(s)
                    if len(key_sentences) >= 5:
                        break
                if not key_sentences:
                    key_sentences = sentences[:3]
                art.summary_ja = " ".join(key_sentences)[:600]
            else:
                art.summary_ja = "(要旨なし)"

    def _fallback_comment(
        self,
        scored_articles: list[SpineScoredArticle],
        duplicates_removed: int,
    ) -> str:
        n = len(scored_articles)
        star_count = sum(1 for a in scored_articles if a.is_star)

        if n == 0:
            return "今週は対象ジャーナルからの新規論文はありませんでした。来週に期待しましょう。"

        parts = []
        if star_count >= 3:
            parts.append(
                f"今週は関心領域の論文が{star_count}件と豊作です！ "
                "じっくりチェックする価値がありそうです。"
            )
        elif star_count >= 1:
            parts.append(
                f"今週は関心領域の論文が{star_count}件あります。"
            )
        else:
            parts.append("今週も脊椎関連の最新論文をお届けします。")

        if duplicates_removed > 0:
            parts.append(f"（過去掲載{duplicates_removed}件は除外済み）")

        return "".join(parts)
