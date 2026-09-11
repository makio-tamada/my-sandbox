# 0001: asyncpg プールの RESET ALL で pgvector の ef_search が消える問題

<!-- ここには動かし方だけを書く。結果と考察は reports/0001-pgvector-pool-guc-reset.md に書く -->

## 動かし方

```shell
uv sync
docker compose up -d
docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 1. 最小再現（データ不要）
uv run repro_guc.py
uv run repro_guc2.py   # 実際にHNSW検索を挟んだ場合の挙動確認

# 2. データ準備（GloVe 100d angular を先頭20,000件だけ使う。ダウンロードは初回のみ）
mkdir -p .data
curl -sL -o .data/glove-100-angular.hdf5 http://ann-benchmarks.com/glove-100-angular.hdf5
uv run python -m src.data_prep

# 3. 計測（3種類）
uv run python -m src.bench_show_dist   # SHOW hnsw.ef_search の分布
uv run python -m src.bench_recall      # recall@10
uv run python -m src.bench_latency     # SET LOCAL のオーバーヘッド

# 4. 完了条件③のpytest
uv run pytest
```

## 依存の追加

```shell
uv add <package>
```

`uv.lock` は再現性のためコミットします。

## 品質チェック

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

`/verify experiments/0001-pgvector-pool-guc-reset` でまとめて実行できます。

## 注意

- `.data/` はダウンロードした GloVe データセットと計測用の中間ファイルを置く場所で、`.gitignore` 済み
- 元Issue（GloVe 300k行・クエリ1000件・SHOW計測200リクエスト）から規模を縮小し、
  corpus 20,000件・クエリ200件・SHOW計測50リクエストで実施した
