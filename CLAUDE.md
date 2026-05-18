# PaperReview

週刊論文レビュー自動投稿システム（NKT + Spine）。

## 週刊スパイン（メルマガ）ルーティン

### 実行手順

1. PubMed検索 + スコアリング:
```bash
python scripts/spine_weekly.py 7 > /tmp/spine_results.json
```

2. 結果JSONを読み取り、Notion MCP (`mcp__Notion__notion-create-pages`) で
   「週刊スパイン（メルマガ）」データベースに投稿する。

### Notion投稿仕様

- **データベース data_source_id**: `72274ed0-2f08-47f5-b8a6-8344a4b65a87`
- **ページ形式**:
  - Issue (title): `Vol.{week} — {year}-W{week:02d}`
  - date:Week:start: その週の月曜日 ISO日付
  - Status: "Draft"
  - Source: "Claude Code"
  - Topics: 全論文の all_topics の和集合（JSON配列文字列）
  - Intro (JP): 気の利いた導入コメント（★件数・注目テーマ・検索期間を含む）
  - Highlights: ★論文の日本語タイトル一覧（箇条書き）
  - Body (JP): 全論文の要約（PMIDを含めること。重複チェックに使用）
  - Papers (list): 全論文の `PMID: {pmid} | DOI: {doi}` 一覧

- **ページコンテンツ**:
  - 冒頭: callout的な導入コメント
  - `## ★ 関心領域` セクション: is_starred=true の論文
  - `## 関心領域外` セクション: is_starred=false の論文
  - 各論文に含める情報:
    - 英語タイトル + 日本語訳（自分で翻訳）
    - 筆頭著者・施設
    - ジャーナル名・巻号・DOI
    - ★の場合: interest_areas を表示
    - 要旨の日本語要約 3〜5行（自分で要約）
    - PubMedリンク

### 重複チェック

投稿前に既存ページの Papers (list) プロパティからPMIDを抽出し、
既出論文は除外する。Notion MCP の `notion-search` または `notion-fetch` で
データベースを参照して確認する。

### ★ 関心領域（4分野）

- **脊椎外科とAI**: deep learning, machine learning, automated, prediction model 等
- **脊椎外科手術の適応評価**: surgical indication, cost-effectiveness, decision-making 等
- **脊椎の基礎研究**: intervertebral disc, spinal cord injury, bone metabolism, osteoclast 等
- **バイオマテリアル**: biomaterial, scaffold, hydroxyapatite, 3D printing 等

### 対象ジャーナル

Spine / The Spine Journal / European Spine Journal / JNS: Spine / Global Spine Journal / JBJS
