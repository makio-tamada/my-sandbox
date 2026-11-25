# 0007: faiss 1.16.0 の HNSW シンク除去リンクと IndexSQFastScan を 1.15.1 と CPU で実測比較

<!-- ここには動かし方だけを書く。結果と考察は reports/0007-faiss-116-hnsw-sq-fastscan.md に書く -->

## 動かし方

2 vCPU の VM で全部で約 25 分。

```shell
# 1. ベクトルを作る（約 1 分）。/usr/local/lib/python3.13 以下の docstring 段落を TF-IDF → SVD(384) → 正規化
uv run make_vectors.py --root /usr/local/lib/python3.13

# 2. 版ごとに計測する（1 回あたり 1.15.1 で約 4 分、1.16.0 で約 6 分）
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench.py --out results/faiss-$v.json
done
# 2 回目（QPS のばらつきを見るため）
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench.py --out results/faiss-$v.run2.json
done

# 3. HNSW を粗量子化器にした IVF（版ごとに約 2 分）
for v in 1.16.0 1.15.1; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench_ivf.py --out results/ivf-$v.json
done

# 4. 1 クエリずつ投げたときのレイテンシ（版ごとに約 1 分）
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench_single.py --out results/single-$v.json
done

# 5. 表にする（標準ライブラリだけ）
python3 summarize.py > results/summary.md
```

| ファイル | 内容 |
| --- | --- |
| `make_vectors.py` | コーパス 10 万件・クエリ 1,000 件・シンク除去用サンプル 1 万件を `data/` に作る（`data/` はコミットしない） |
| `bench.py` | Flat / SQ8 / SQFastScan（1.16.0 のみ）/ HNSW（3 モード）を 1,000 クエリ 1 バッチで計測 |
| `bench_ivf.py` | IVF4096 + HNSW 粗量子化器。1.16.0 は既定とシンク除去リンクを切った対照の 2 通り |
| `bench_single.py` | Flat / SQ8 / SQFastScan を 1 クエリずつ投げたときの p50・p95 |
| `summarize.py` | `results/*.json` から `results/summary.md` を作る |

`results/data_meta.json` は手順 1 の `data/meta.json` の写し（段落数・ベクトルのハッシュ）。
