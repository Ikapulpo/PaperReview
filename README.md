# 週刊NKT（メルマガ）- NKT細胞論文 自動レビューシステム

PubMedからNKT細胞関連の最新論文を毎週自動検索し、研究室の研究テーマとの関連度でランキングして、Notionの「週刊NKT（メルマガ）」データベースにニュースレター形式で自動投稿するシステムです。

## 機能

- **PubMed自動検索**: NKT細胞（mouse/human中心）の論文を週次で検索
- **関連度スコアリング**: 13のトピックに対して自動分類・スコアリング
- **Notionメルマガ投稿**: 週1回、まとめてニュースレター形式で自動登録
- **手法・コンセプト解析**: 論文の手法と概念から研究への応用可能性を評価

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

「週刊NKT（メルマガ）」データベースは既に作成済みです（ID: `a1f5b30f...`）。
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

## Notionデータベース構造（メルマガ形式）

1週間分の論文を1ページにまとめて投稿:

| プロパティ | 内容 |
|---|---|
| Issue | 号タイトル（例: Vol.15 — 2026-W15） |
| Week | 基準日（月曜） |
| Status | Draft → Editing → Published |
| Topics | 全論文のトピック集約 |
| Intro (JP) | 全体サマリ |
| Highlights | 見出し箇条書き |
| Body (JP) | 各論文の短いサマリ |
| Papers (list) | 論文リスト（PMID/DOI/URL） |

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
│   │   └── relevance.py     # 関連度スコアリングエンジン（13トピック）
│   ├── notion/
│   │   └── client.py        # Notionメルマガ投稿クライアント
│   └── scheduler/
│       └── runner.py        # 週次スケジューラ
├── pyproject.toml
├── .env.example
└── README.md
```
