# 0008: 合成クエリで評価した RAG 検索構成の優劣は、人間のクエリでも保たれるか

<!-- ここには動かし方だけを書く。結果と考察は reports/0008-rag-synthetic-query-gap.md に書く -->

対応 Issue: #19（旧設計は #10）

## 準備

1. Claude の呼び出し方法を決める（Issue #19「着手前に決めること」）
   - 直接 API: リポジトリ直下の `.env.example` を `.env` にコピーし、`ANTHROPIC_API_KEY` を設定する。`.env` はコミットされない
   - Vertex AI: `gcloud auth application-default login` で ADC を設定する。モデルのクォータが承認済みであることを確認する
2. モデル ID は `claude-api` スキルで現行 ID を確認してから `config.py` に書く

## 動かし方

検証スクリプトは未実装です（Issue #19 の「実装方針」に従って追加する）。実装後は段階的に実行します。

```shell
uv run run_query_gap.py --pairs 5     # 試走
uv run run_query_gap.py --pairs 30    # 全工程
uv run run_query_gap.py --pairs 200   # 時間が残れば拡大
```

## ファイル

| ファイル | 役割 |
| --- | --- |
| `config.py` | モデル ID とパラメータ。比較検証ではここだけ差し替える |
| `client.py` | `.env` の読み込みとクライアント生成 |
| `main.py` / `tool_use.py` | 雛形のまま（疎通確認用） |
| `runs/` | クエリ単位の生ログ（JSONL）、生成した合成クエリ、プロンプト |

## 検証するときの注意

- **モデル ID を記憶で書かない。** `claude-api` スキルで現行の ID と料金を確認する
- 閾値は開発用データで決めて固定する。評価用データで調整し直さない
- SQuAD のクエリは「文書を見て書かれた人間のクエリ」と呼ぶ

詳しい作法は `$llm-experiment` スキルを参照してください。
