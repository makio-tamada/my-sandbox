# 0005: 合成クエリと実クエリのRecall@5ギャップ + クエリ拡張のエスカレーション比較

<!-- ここには動かし方だけを書く。結果と考察は reports/0005-synthetic-query-gap.md に書く -->

## 準備

### 1. GCP(Vertex AI)の認証

このスクリプトは `ANTHROPIC_API_KEY` を使わず、GCPのADC経由でClaude(Vertex AI)を呼び出す。

```shell
gcloud auth application-default login
gcloud config set project solution-projects-509006
```

対象プロジェクト`solution-projects-509006`は、`aiplatform.googleapis.com`の有効化・課金アカウントの紐付けは済んでいるが、
**`anthropic-claude-haiku-4-5`のオンライン予測クォータが新規プロジェクトのため既定0で、GCPコンソールでの引き上げ申請が承認されるまで実行できない**(2026-09-18時点)。

### 2. DBを立てる

```shell
docker compose up -d
docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

## 動かし方

```shell
uv run run_query_gap.py | tee run_log.txt
```

`run_query_gap_results.csv` にクエリ単位の結果(query_set / config / hit / latency_ms / llm_calls / escalated / top1_similarity)が出力される。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `compose.yaml` | pgvector(pg17)。ポート5435(他検証は5433/5434を使用中のため) |
| `run_query_gap.py` | データ準備・合成クエリ生成・baseline/always_expand/escalateの3構成実行・集計 |

## 検証するときの注意

- **モデル ID を記憶で書かない。** `claude-api` スキルで現行の ID を確認する。Vertex AIでは直接APIと異なり日付なしの裸ID(`claude-haiku-4-5`)を使う
- `.env` は使わない(Vertex AIはGCPのADCで認証するため)。APIキーの管理は発生しない
- 1回の出力を結論にしない。合成クエリ生成やクエリ拡張の出力揺らぎがあるため、異常な値が出たら`run_log.txt`で個別クエリを確認する

詳しい作法は `$llm-experiment` スキルを参照してください。
