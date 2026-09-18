# 0001: asyncpg プールの RESET ALL で pgvector の ef_search が消える問題

**結論**: `init=` だけの asyncpg プールは 2 回目以降の acquire で `hnsw.ef_search` が消え（`40` に戻り）、recall@10 が 97.95%→86.05%（約11.9pt）落ちる。`init=`+`setup=` / `server_settings=` / `PGOPTIONS` / `SET LOCAL` の4戦略はいずれも劣化を防げるが、`SET LOCAL` はトランザクション1本あたり p50 で約1.1ms（素のSELECTの約2.5倍）のオーバーヘッドがある。

| 項目 | 値 |
| --- | --- |
| Issue | #3 |
| PR | (このレポートと同じPRで作成) |
| 実施日 | 2026-09-11 |
| 種別 | python-project |
| 状態 | ✅ 完了 |
| コード | [experiments/0001-pgvector-pool-guc-reset/](../experiments/0001-pgvector-pool-guc-reset/) |

## 何を確かめたかったか

asyncpg のコネクションプールは、接続をプールへ返す際に `RESET ALL` を発行する。`create_pool(init=...)` で `SET hnsw.ef_search = 200` を1回だけ設定するよくある実装が、2回目以降の acquire でこの設定を静かに失うのか、失うなら pgvector の recall@10 が実際にどれだけ落ちるのかを、GloVeの公開ベクトルデータセットで実測することが目的。

## 前提・計測環境

| 項目 | 内容 |
| --- | --- |
| マシン | Apple M4 Max (arm64) |
| Python | 3.12.8（`uv run`） |
| 主要ライブラリ | asyncpg 0.31.0 / numpy 2.5.3 / h5py 3.16.0 |
| DB | `pgvector/pgvector:pg17`（PostgreSQL 17.11、Docker） |
| データセット | GloVe 100d angular (ANN-Benchmarks)。**元Issueの計画（先頭300,000件）から規模を縮小し、先頭20,000件のみを使用** |
| クエリ数 | 200件（元Issueの計画は1,000件。縮小） |
| SHOW分布の試行回数 | 各(戦略, max_size)の組につき50同時リクエスト（元Issueの計画は200。縮小） |
| 試行回数 | 上記の通り。複数回の繰り返し試行はしておらず、各計測は1回のみ（**未検証**: 複数回実行したときのばらつき） |

## 手順（再現方法）

```shell
cd experiments/0001-pgvector-pool-guc-reset
uv sync
docker compose up -d
docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"

uv run repro_guc.py
uv run repro_guc2.py

mkdir -p .data
curl -sL -o .data/glove-100-angular.hdf5 http://ann-benchmarks.com/glove-100-angular.hdf5
uv run python -m src.data_prep

uv run python -m src.bench_show_dist
uv run python -m src.bench_recall
uv run python -m src.bench_latency

uv run pytest
```

## 結果

### 1. 最小再現（`repro_guc.py`）

コード直下の芯となる結果。`init only` は3回目のacquireまでに空文字列に落ちる:

```
init only: acquire 1/2/3 = ['200', '', '']
init+setup: acquire 1/2/3 = ['200', '200', '200']
server_settings: acquire 1/2/3 = ['200', '200', '200']
```

**仮説（`40`に戻る）とは異なり、実際には空文字列 `''` に戻った。** これは、このセッションで一度も実際の vector 検索クエリを実行していなかったため、pgvector の拡張モジュールがそのバックエンドプロセスにまだロードされておらず、`hnsw.ef_search` が「本物のGUC」ではなく「プレースホルダGUC」のままだったことが原因と判明した（`repro_guc2.py` で追加検証）。

### 1'. 実際にHNSW検索を挟んだ場合（`repro_guc2.py`）

同じ接続で実際に vector 型を使う検索クエリを1回実行してから `RESET ALL` を発生させると、仮説通り pgvector のデフォルト値 `40` に戻ることを確認した:

```
1st acquire (vector query 実行後): 200
2回目 acquire: 40
3回目 acquire: 40
```

> **補足（想定外の発見）**: pgvector のカスタムGUC（`hnsw.ef_search` 等）は、拡張モジュールがそのPostgreSQLバックエンドプロセスに実際にロードされるまで「本物のGUC」として登録されない。`CREATE EXTENSION` を実行しても、新しい接続（＝新しいバックエンドプロセス）ではまだロードされておらず、`SHOW hnsw.ef_search` は `unrecognized configuration parameter` エラーになる。`SET hnsw.ef_search = 200` はドット区切り名のため「プレースホルダGUC」として常に成功するが、実際にHNSW検索（vector型を使うクエリ）を実行して初めてモジュールがロードされ、その時点でプレースホルダの値が実際のGUCの初期値として引き継がれる。この経路の違いが、`RESET ALL` 後の戻り先（空文字列 vs `40`）を分ける。本番のRAG/検索アプリケーションは接続のたびに実際の検索クエリを実行するため、実務上は「`40`に戻る」という元の仮説の通りになる。

### 2. SHOW hnsw.ef_search の分布（`bench_show_dist.py`、実際に検索クエリを挟んで計測）

同時リクエスト数 = `max_size` で50リクエストを流したときの結果:

| 戦略 | max_size=1 | max_size=5 | max_size=20 |
| --- | --- | --- | --- |
| init only | 98.0% が非200 (1/50成功) | 90.0% が非200 (5/50成功) | 60.0% が非200 (20/50成功) |
| init+setup | 0.0% | 0.0% | 0.0% |
| server_settings | 0.0% | 0.0% | 0.0% |
| pgoptions (`options=-c hnsw.ef_search=200`) | 0.0% | 0.0% | 0.0% |
| SET LOCAL (per-query) | 0.0% | 0.0% | 0.0% |

`init only` は「最初の max_size 件だけ 200 で、それ以降は 100% が `40`」という仮説通りのパターンになった。`server_settings=` と `PGOPTIONS` は起動パケットのランタイムパラメータとして扱われ、`RESET ALL` 後もそのセッションの既定値として残り続けるため、どちらも劣化しなかった（両者に差はなかった）。

### 3. recall@10（`bench_recall.py`、200クエリ、プールmax_size=5で同時実行）

| 戦略 | recall@10（全体平均） | 先頭5件の平均 | 6件目以降の平均 |
| --- | --- | --- | --- |
| init only | **0.8605** | 1.0000 | 0.8569 |
| init+setup | 0.9795 | 1.0000 | 0.9790 |
| server_settings | 0.9795 | 1.0000 | 0.9790 |
| pgoptions | 0.9795 | 1.0000 | 0.9790 |
| SET LOCAL (per-query) | 0.9795 | 1.0000 | 0.9790 |

`init only` は健全な戦略（97.95%）に比べ recall@10 が **11.9pt** 低い。仮説「5〜15pt程度の差」の範囲内に収まった。先頭5件（プール暖機直後、まだ全接続が `ef_search=200` のまま）は全戦略で recall@10=1.0 になっており、「プールが暖まった直後は問題が起きない」という劣化の性質を裏付けている。

### 4. SET LOCAL のオーバーヘッド（`bench_latency.py`、200クエリ、単一接続で逐次実行）

| | p50 (ms) | p95 (ms) | mean (ms) |
| --- | --- | --- | --- |
| 素の SELECT | 0.749 | 0.890 | 0.754 |
| BEGIN; SET LOCAL; SELECT; COMMIT; | 1.854 | 2.072 | 1.853 |
| **オーバーヘッド** | **+1.105** | **+1.182** | - |

**仮説（p50で1ms未満）は外れた。** 実測では p50 で約1.1ms、素のSELECTの約2.5倍のオーバーヘッドがあった。絶対値としては小さいが「タダ」ではない。トランザクション開始・SET LOCAL・COMMIT の3往復のオーバーヘッドが、今回の非常に軽いクエリ（20,000件・100次元のHNSW検索、0.75ms程度）に対して相対的に大きく見えている可能性がある。

### 5. pytest（完了条件③）

```
tests/test_pool_guc.py::test_init_setup_keeps_ef_search_across_acquires PASSED
tests/test_pool_guc.py::test_init_only_does_not_keep_ef_search_across_acquires XFAIL
1 passed, 1 xfailed
```

`init=` だけの実装で checkout 後に `SHOW hnsw.ef_search == '200'` が実際に落ちることを確認した上で、`pytest.mark.xfail(strict=True)` として明示的にマークしてある（`strict=True` のため、将来この欠陥が意図せず直った場合はテストが失敗しCIで検知できる）。

## 考察

- **`init=` のみの実装は本番で確実に踏む地雷。** プール暖機直後（先頭 max_size 件）は正しく動くため、開発時の簡単な動作確認ではまず気づけない。max_size が大きいほど「壊れているリクエストの割合」自体は下がって見える（60%まで下がる）が、絶対数は増えるため実運用上の危険度は変わらない
- **`init=`+`setup=` / `server_settings=` / `PGOPTIONS` は同格。** 起動パケット経由（`server_settings` / `PGOPTIONS`）と、acquireのたびに再設定する方式（`setup=`）はいずれも RESET ALL の影響を受けず、recall・SHOW分布とも完全に一致した。プール全体で固定値にしてよいなら `server_settings=` が最もシンプル（コード変更なしで済む）
- **`SET LOCAL` はクエリ単位で値を変えたい場合の唯一の選択肢だが、無料ではない。** p50で+1.1msのオーバーヘッドは今回の検証環境（ローカルDocker、20,000件のHNSW検索）では相対的に大きく出た。より重いクエリやネットワーク越しの接続ではこの絶対値の比重は下がると推測されるが、それ自体は**未検証**
- **pgvectorのカスタムGUCはセッションごとに拡張モジュールがロードされるまで有効にならない**という副次的な発見があった。これは今回の主目的（RESET ALL問題）には影響しなかったが（実際の検索クエリを挟めば必ずロードされるため）、`SHOW` だけで動作確認しようとすると誤解を招きやすい注意点として記録しておく

## 未検証・残課題

- GloVeを元Issue通りの規模（300,000件・クエリ1,000件）で実行した場合の数値（今回は20,000件・200クエリに縮小）
- 各計測の複数回試行によるばらつき（今回は1回のみ）
- `pgbouncer`（session / transaction pooling）を挟んだ場合の挙動（元Issューでも明示的にスコープ外）
- `SET LOCAL` のオーバーヘッドが、より重いクエリやリモートDB接続でも同程度の相対比になるか
- `create_pool(server_settings={"hnsw.ef_search": "200"})` で `UndefinedObjectError` が出るケース — 今回の環境（pgvector拡張が先にCREATE EXTENSION済みの状態）では発生せず、成功した。拡張未作成の状態から`server_settings`で起動した場合の挙動は未検証

## 参考リンク

- https://github.com/vectorize-io/hindsight/pull/2815
- https://github.com/vectorize-io/hindsight/pull/3491
- https://github.com/magicstack/asyncpg/issues/541
- https://github.com/pgbouncer/pgbouncer/issues/525
- https://github.com/plastic-labs/honcho/pull/1091
- https://github.com/metabase/metabase/pull/75722
- https://github.com/pgvector/pgvector
