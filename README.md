# 週刊NKT - NKT細胞論文 自動レビューシステム

PubMedからNKT細胞関連の最新論文を毎週自動検索し、研究室の研究テーマとの関連度でランキングしてNotionに投稿するシステムです。

## 機能

- **PubMed自動検索**: NKT細胞（mouse/human中心）の論文を週次で検索
- **関連度スコアリング**: 以下の研究テーマとの関連度を自動スコアリング
  - NKT恒常性維持機能
  - NKTワクチン
  - 整形外科
  - 骨代謝
- **Notion自動投稿**: 「週刊NKT」データベースにサマリを自動登録
- **手法・コンセプト解析**: 論文の手法と概念から研究への応用可能性を評価

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -e .
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して以下を設定:

```
NOTION_API_KEY=your_notion_integration_token
NOTION_DATABASE_ID=your_database_id
NCBI_API_KEY=optional_for_higher_rate_limit
```

### 3. Notion側の準備

1. [Notion Integrations](https://www.notion.so/my-integrations) で新しいインテグレーションを作成
2. 「週刊NKT」データベースを作成し、以下のプロパティを追加:
   - `タイトル` (Title型) - 自動生成される週ラベル
   - `期間` (Rich Text型) - 検索期間
   - `論文数` (Number型) - 取得論文数
   - `ステータス` (Select型) - 新規/確認済
3. データベースにインテグレーションを接続
4. データベースIDを `.env` に設定

## 使い方

### 今すぐ実行

```bash
# PubMed検索 + Notion投稿
paper-review run

# 過去14日間で検索
paper-review run --days 14

# 検索のみ (Notion投稿なし)
paper-review search
```

### 自動スケジュール

```bash
# 毎週月曜 9:00 に自動実行 (デフォルト)
paper-review schedule
```

`.env` でスケジュールをカスタマイズ:
```
SCHEDULE_DAY=monday
SCHEDULE_TIME=09:00
```

### Notion接続テスト

```bash
paper-review verify
```

## スコアリングの仕組み

各論文は以下の3軸で評価されます:

1. **キーワードマッチ**: タイトル(×3)、アブストラクト(×1.5)、MeSH/キーワード(×0.5)
2. **手法の関連性**: in vivo/in vitro、フローサイトメトリー、シーケンシング、骨代謝アッセイなど
3. **コンセプトブリッジ**: 免疫制御、腫瘍免疫、骨免疫学、細胞治療、組織恒常性

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
│   │   └── relevance.py     # 関連度スコアリングエンジン
│   ├── notion/
│   │   └── client.py        # Notion APIクライアント
│   └── scheduler/
│       └── runner.py        # 週次スケジューラ
├── pyproject.toml
├── .env.example
└── README.md
```
