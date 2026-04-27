# 週刊NKT（メルマガ）- NKT細胞論文 自動レビューシステム

PubMedからNKT細胞関連の最新論文を毎週自動検索し、研究室の研究テーマとの関連度でランキングして、Notionの「週刊NKT」データベースにニュースレター形式で自動投稿するシステムです。

## 機能

- **PubMed自動検索**: NKT細胞（mouse/human中心）の論文を週次で検索
- **関連度スコアリング**: 13のトピック + 4つの研究領域 + 13の実験手法で自動分類・スコアリング
- **手法・コンセプト解析**: 論文の実験手法を検出し、研究への応用可能性を日本語で提示
- **おすすめ順表示**: 複合スコア（トピック×研究領域×手法）でランキング
- **Notion自動投稿**: 週1回、研究領域別サマリ・手法別サマリ付きでニュースレター投稿

### 4つの研究領域

| 研究領域 | 説明 |
|---|---|
| NKT恒常性維持 | NKT細胞が生体内でどのように維持されるかの機構研究 |
| NKTワクチン | NKT細胞を利用したワクチン・細胞治療の開発研究 |
| 整形外科 | 整形外科疾患・手術における免疫応答と骨・関節の研究 |
| 骨代謝研究 | 骨のリモデリング機構と骨免疫学の基礎研究 |

### 13の実験手法カテゴリ

フローサイトメトリー、マスサイトメトリー (CyTOF)、シングルセル解析、空間トランスクリプトーム、in vivoモデル、骨解析、細胞培養・拡大培養、臨床試験・トランスレーショナル、遺伝子操作・CRISPR、イメージング、バイオインフォマティクス、機能アッセイ、DC負荷・ワクチン調製

### 対応トピック

| トピック | 説明 |
|---|---|
| iNKT development | NKT細胞の分化・恒常性維持 |
| Thymus / development | 胸腺でのNKT発生 |
| NKT-B cell | NKTとB細胞の相互作用 |
| B cell tolerance | B細胞トレランス |
| Osteoimmunology | 骨免疫学 |
| Autoimmunity / SLE | 自己免疫・SLE |
| Metabolism | 代謝 |
| Tumor immunity | 腫瘍免疫・NKTワクチン |
| Infection | 感染症 |
| Cytokines (IL-4/IFNγ) | サイトカイン |
| TCR repertoire | TCRレパトア |
| Methods / Omics | 実験手法 |
| scRNA-seq / spatial | シングルセル・空間解析 |

## セットアップ

### 1. インストール

```bash
pip install -e .
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集:

```
NOTION_API_KEY=your_notion_integration_token
NCBI_API_KEY=optional_for_higher_rate_limit
```

### 3. Notion側の準備

「週刊NKT」データベースは既に作成済みです（ID: `a1f5b30f...`）。
Notion Integrationを接続し、APIキーを `.env` に設定してください。

## 使い方

```bash
# PubMed検索 + Notion投稿
paper-review run

# 過去14日間で検索
paper-review run --days 14

# 検索のみ（Notion投稿なし）
paper-review search

# 毎週自動実行
paper-review schedule

# Notion接続テスト
paper-review verify
```

## スコアリングの仕組み

各論文は3つの次元で評価され、複合スコアで順位付けされます:

1. **トピックスコア (40%)**: 13の研究トピックに対するキーワードマッチング
2. **研究領域スコア (45%)**: 4つのラボ研究領域との関連度
3. **手法ボーナス (15%)**: 検出された実験手法の数と関連性

各論文には日本語のおすすめ理由が生成されます:
- どの研究領域に関連するか
- どの手法が使われていて、研究にどう活かせるか
- 手法と研究領域のクロスリファレンス

## Notionデータベース構造（メルマガ形式）

1週間分の論文を1ページにまとめて投稿:

| プロパティ | 内容 |
|---|---|
| Issue | 号タイトル（例: Vol.15 — 2026-W15） |
| Week | 基準日（月曜） |
| Status | Draft → Editing → Published |
| Topics | 全論文のトピック集約 |
| Intro (JP) | 全体サマリ（研究領域別・手法別のハイライト含む） |
| Highlights | 見出し箇条書き |
| Body (JP) | 各論文の短いサマリ（おすすめ理由付き） |
| Papers (list) | 論文リスト（PMID/DOI/URL） |

ページ本文には以下のセクションが含まれます:
- 📌 研究領域別サマリ（4領域ごとの該当論文一覧）
- 🔬 検出された手法（手法ごとの該当数と活用提案）
- 📊 トピック別サマリ
- 各論文の詳細（おすすめ理由のcallout付き）

## プロジェクト構成

```
PaperReview/
├── src/
│   ├── cli.py              # CLIインターフェース
│   ├── config.py            # 設定管理
│   ├── pipeline.py          # メインパイプライン
│   ├── pubmed/
│   │   └── client.py        # PubMed E-utilities クライアント
│   ├── scorer/
│   │   └── relevance.py     # 関連度スコアリングエンジン（トピック・手法・研究領域）
│   ├── notion/
│   │   └── client.py        # Notionメルマガ投稿クライアント
│   └── scheduler/
│       └── runner.py        # 週次スケジューラ
├── pyproject.toml
├── .env.example
└── README.md
```
