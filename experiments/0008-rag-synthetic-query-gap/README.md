# 0008: 合成クエリで評価した RAG 検索構成の優劣は、人間のクエリでも保たれるか

<!-- ここには動かし方だけを書く。結果と考察は reports/0008-rag-synthetic-query-gap.md に書く -->

対応 Issue: #19（旧設計は #10）

## 準備

1. リポジトリ直下の `.env.example` を `.env` にコピーし、`ANTHROPIC_API_KEY` を設定する。`.env` はコミットされない
2. 実行前に `claude-api` スキルで現行のモデル ID を確認し、`config.py` の `MODEL_ID` と一致していることを確かめる
3. Hugging Face（SQuAD と埋め込みモデルの取得元）に接続できる環境で実行する。初回は約 90MB のモデルと数十 MB のデータをダウンロードする

DB（pgvector）は使わない。Recall を測る検証なので、近似による取りこぼしを避け、numpy で全件の類似度を計算する厳密検索にしている。

## 動かし方

```shell
cd experiments/0008-rag-synthetic-query-gap

# 動作確認（API・ダウンロードなし。数値に意味はない。出力はコミットされない）
python3 run_query_gap.py --fake --pairs 5

# 本番（段階方式）
uv run run_query_gap.py --pairs 5     # 試走
uv run run_query_gap.py --pairs 30    # 全工程
uv run run_query_gap.py --pairs 200   # 時間が残れば拡大
```

`--pairs` は評価用のペア数。開発用（閾値を決める）のペア数は既定で同じ数（最大 100）になり、`--dev-pairs` で変えられる。

## 出力

| パス | 中身 |
| --- | --- |
| `runs/<日時>-pairs<N>/summary.json` | 指標・95% 信頼区間・構成の順位・ペア比較・改善悪化・閾値曲線・特徴量 |
| `runs/<日時>-pairs<N>/queries.jsonl` | クエリ単位の生ログ（開発用・評価用の両方） |
| `runs/<日時>-pairs<N>/config_snapshot.json` | 実行時の設定（プロンプト全文を含む） |
| `runs/cache/llm_cache.jsonl` | LLM のリクエストと応答（合成クエリ・言い換え・トークン数）。再実行時はここから再利用する |

標準出力には、主結果の表（Markdown）が出る。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `config.py` | モデル ID・プロンプト・分割・検索・統計の設定。実行前に固定する |
| `run_query_gap.py` | データ準備・合成クエリ生成・3 構成の評価・閾値決定・集計 |
| `client.py` | `.env` の読み込みとクライアント生成 |
| `main.py` / `tool_use.py` | 雛形のまま（API の疎通確認に使える） |

## 検証するときの注意

- **モデル ID を記憶で書かない。** `claude-api` スキルで現行の ID と料金を確認する
- 閾値は開発用データで決めて固定する。評価用データで調整し直さない
- SQuAD のクエリは「文書を見て書かれた人間のクエリ」と呼ぶ
- LLM の出力は揺らぐ。キャッシュを消して再実行すると合成クエリが変わるので、本番の数値は 1 回の実行で生成したキャッシュに固定して扱う

詳しい作法は `$llm-experiment` スキルを参照してください。
