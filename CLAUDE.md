# PaperReview — 週刊NKT自動レビューシステム

## 概要

毎週PubMedからNKT細胞関連の最新論文を検索し、研究室の研究テーマとの関連度でスコアリング・ランキングして、Notionの「週刊NKT（メルマガ）」データベースに自動投稿する。

## 研究室の研究テーマ

- **NKT恒常性維持機能**: iNKT細胞の分化・サブセット維持・組織resident NKT
- **NKTワクチン**: α-GalCer、CD1d、腫瘍免疫、CAR-NKT、細胞治療
- **整形外科**: 骨関連免疫、関節疾患
- **骨代謝研究**: 破骨細胞/骨芽細胞、RANKL/OPG、osteoimmunology

## Notionデータベース

- DB名: 週刊NKT（メルマガ）
- DB ID: `a1f5b30f-0402-4ddf-a872-c42622d9c27c`
- Data Source: `collection://5e5eca70-b1c4-4039-92fe-a92fcf8d21a0`

## 週次レビュー実行手順（Claude Code scheduled routine）

1. **PubMed検索**: `mcp__PubMed__search_articles` で過去7日間のNKT論文を検索
   - クエリ: `("NKT cell" OR "NKT cells" OR "natural killer T cell" OR "iNKT" OR "invariant NKT" OR "CD1d-restricted") AND ("mouse" OR "mice" OR "murine" OR "human" OR "patient" OR "clinical")`
2. **メタデータ取得**: `mcp__PubMed__get_article_metadata` で全論文の詳細を取得
3. **重複チェック**: 前号のNotionページからPMIDを取得し、既出論文を除外
4. **スコアリング**: `src/scorer/relevance.py` の13トピックプロファイルに基づいて関連度を評価
5. **分析**: 各論文について概要・当研究室への示唆（Method、コンセプト）を作成
6. **Notion投稿**: `mcp__Notion__notion-create-pages` で週刊号を作成
7. **通知**: PushNotification で結果サマリを送信

## スコアリングトピック（13分類）

iNKT development, Thymus / development, NKT-B cell, B cell tolerance,
Osteoimmunology, Autoimmunity / SLE, Metabolism, Tumor immunity,
Infection, Cytokines (IL-4/IFNγ), TCR repertoire, Methods / Omics,
scRNA-seq / spatial

## 号のフォーマット

- Issue: `Vol.{week_num} — {year}-W{week_num}`
- Week: その週の月曜日
- Status: Draft
- Source: Claude Code
