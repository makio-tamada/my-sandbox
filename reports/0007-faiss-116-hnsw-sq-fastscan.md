# 0007: faiss 1.16.0 の HNSW シンク除去リンクと IndexSQFastScan を 1.15.1 と CPU で実測比較

**結論**: 1.16.0 では 8bit スカラー量子化（SQ8）の総当たり検索が 1.15.1 の約 2.1 倍に速くなり、新しい `IndexSQFastScan` は SQ8 と同じ 38.4 MB のまま recall@10 を 0.5pt 落とすだけで SQ8 の約 4 倍速い。一方、HNSW の「シンク除去リンク」は単体の `IndexHNSWFlat` の `add()` では入らず、明示的に呼んでも 10 万件では recall@10 が変わらなかった

| 項目 | 値 |
| --- | --- |
| Issue | #17 |
| PR | #18 |
| 実施日 | 2026-11-25 |
| 種別 | python-script |
| 状態 | ✅ 完了 |
| コード | [experiments/0007-faiss-116-hnsw-sq-fastscan/](../experiments/0007-faiss-116-hnsw-sq-fastscan/) |

## 何を確かめたかったか

faiss 1.16.0（2026-11-09 リリース）のリリースノートには、RAG のベクトル検索に効きそうな CPU 向けの変更が並んでいる。そのうち次の 3 つが、同じデータ・同じマシンで 1.15.1 と比べてどれだけ効くかを確かめたかった。

1. **HNSW のシンク除去リンク**（#5705 / #5789）。level-0 にサンプルからのリンクを足し、探索が「シンク」（近くないのに抜け出せないノード）で止まらないようにする。既定でノードあたり 3 サンプル
2. **x86 の 8bit スカラー量子化の内積距離の高速化**（#5829）
3. **`IndexSQFastScan`**（#5341）。8bit コードを 4bit に再量子化して SIMD で走査し、元の 8bit で再ランクする新しい索引

仮説は次のとおりだった。

- 1.16.0 の HNSW は `efSearch=16` の recall@10 が 1pt 以上上がり、構築時間が 1 割以上延びる
- SQ8 の総当たり検索は 1.2 倍以上速くなる
- `IndexSQFastScan` は SQ8 より 2 倍以上速く、recall@10 の低下は 1pt 未満

## 前提・計測環境

| 項目 | 内容 |
| --- | --- |
| マシン | クラウドの Linux VM、Intel Xeon @ 2.10GHz × 2 vCPU（AVX2 / AVX-512 / AVX-512 FP16 あり）、メモリ 7.8 GiB |
| Python | 計測: 3.13.18（`uv run --no-project --python 3.13`）。ベクトル作成: 3.12.3（`uv run make_vectors.py` のスクリプト環境） |
| 主要ライブラリ | faiss-cpu 1.15.1 / 1.16.0（PyPI の wheel。どちらも `OPTIMIZE DD AVX2 AVX512 AVX512_SPR AVX512_VPOPCNT`）、numpy 2.5.3（計測）、numpy 2.5.5・scikit-learn 1.9.1・scipy 1.18.1（ベクトル作成）、uv 0.11.32 |
| データ規模 | コーパス 100,000 件 × 384 次元（float32、153.6 MB）、クエリ 1,000 件、シンク除去用サンプル 10,000 件（3 つは重ならない） |
| ベクトルの作り方 | `/usr/local/lib/python3.13` 以下の `.py` の docstring を空行で段落に分け、40 文字以上・重複除去で 150,860 段落。シード 0 で 111,000 件を抽出 → TF-IDF（語彙 30,618）→ TruncatedSVD 384 次元（説明分散 35.1%）→ L2 正規化。内積 = コサイン類似度 |
| 正解 | `IndexFlatIP` の上位 10 件。recall@10 はその一致率の平均 |
| 試行回数 | バッチ検索: 1,000 クエリを 1 バッチで投げて 5 回の中央値。これを版ごとに 2 回実行（表の「/」区切り）。単発検索: 300 クエリを 1 件ずつ、3 回。検索は 1 スレッド（明記したものは 2 スレッド）、構築は 2 スレッド |

**Hugging Face Hub に届かない環境だったため、ニューラル埋め込みではなく TF-IDF + SVD（LSA）のベクトルを使っている。** ベクトルの分布（固有値の減り方、クラスタのまとまり方）は文埋め込みモデルの出力と違うので、recall の絶対値はそのまま実運用の目安にはならない。版どうし・索引どうしの比較に使う。

## 手順（再現方法）

```shell
cd experiments/0007-faiss-116-hnsw-sq-fastscan
uv run make_vectors.py --root /usr/local/lib/python3.13
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench.py --out results/faiss-$v.json
done
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench.py --out results/faiss-$v.run2.json
done
for v in 1.16.0 1.15.1; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench_ivf.py --out results/ivf-$v.json
done
for v in 1.15.1 1.16.0; do
  uv run --no-project --python 3.13 --with faiss-cpu==$v --with numpy python bench_single.py --out results/single-$v.json
done
python3 summarize.py > results/summary.md
```

生データは `experiments/0007-faiss-116-hnsw-sq-fastscan/results/*.json`、全部の表は `results/summary.md` にある。

## 結果

### 測りたかった数字 3 つ

| # | 数字 | 1.15.1 | 1.16.0 | 差 |
| --- | --- | --: | --: | --- |
| 1 | HNSW（M=32）`efSearch=16` の recall@10 | 0.9038 | 0.9038（明示的にシンク除去リンクを足すと 0.9039） | **変わらない** |
| 2 | SQ8 総当たりの QPS（1 スレッド、1,000 クエリ 1 バッチ） | 144 / 163 | 338 / 326 | **約 2.1 倍** |
| 2' | SQ8 総当たりの 1 クエリあたり p50 | 6.29 ms | 2.95 ms | **約 2.1 倍** |
| 3 | `IndexSQFastScan`（QT_8bit、既定の rerank_factor=2）vs SQ8（同じ 1.16.0） | — | QPS 1,389 / 1,268 vs 338 / 326、recall@10 0.9684 vs 0.9735、サイズ 38.4 MB vs 38.4 MB | **約 4 倍速、−0.51pt、メモリ同じ** |

### 総当たり（1,000 クエリを 1 バッチ）

| 版 | 索引 | スレッド | QPS（1 回目 / 2 回目） | recall@10 | 索引サイズ |
| --- | --- | --: | --: | --: | --: |
| 1.15.1 | Flat | 1 | 397 / 354 | 1.0000 | 153.6 MB |
| 1.15.1 | SQ8 | 1 | 144 / 163 | 0.9735 | 38.4 MB |
| 1.15.1 | SQ8 | 2 | 300 / 362 | 0.9735 | 38.4 MB |
| 1.16.0 | Flat | 1 | 414 / 415 | 1.0000 | 153.6 MB |
| 1.16.0 | SQ8 | 1 | 338 / 326 | 0.9735 | 38.4 MB |
| 1.16.0 | SQ8 | 2 | 674 / 692 | 0.9735 | 38.4 MB |

### IndexSQFastScan（1.16.0、1 スレッド、1,000 クエリを 1 バッチ）

| qtype | rerank_factor | QPS（1 回目 / 2 回目） | recall@10 | 索引サイズ |
| --- | --: | --: | --: | --: |
| QT_8bit | 1 | 1,386 / 1,453 | 0.8594 | 38.4 MB |
| QT_8bit | 2（既定） | 1,389 / 1,268 | 0.9684 | 38.4 MB |
| QT_8bit | 4 | 1,227 / 1,196 | 0.9708 | 38.4 MB |
| QT_8bit | 8 | 1,097 / 1,076 | 0.9718 | 38.4 MB |
| QT_4bit | 2（既定） | 1,423 / 1,352 | 0.8516 | 19.2 MB |

2 スレッドでは QT_8bit・rerank_factor=2 で 2,846 / 2,545 QPS（ほぼ 2 倍）。

### 1 クエリずつ投げたとき（1 スレッド、300 クエリ × 3 回）

| 版 | 索引 | p50（ms、3 回） | p95（ms、3 回） |
| --- | --- | --: | --: |
| 1.15.1 | Flat | 13.15 / 12.28 / 12.99 | 15.94 / 14.72 / 15.04 |
| 1.15.1 | SQ8 | 6.63 / 5.87 / 6.29 | 11.45 / 6.39 / 10.62 |
| 1.16.0 | Flat | 13.09 / 12.93 / 13.24 | 15.43 / 15.21 / 15.69 |
| 1.16.0 | SQ8 | 3.12 / 2.95 / 2.95 | 3.81 / 4.25 / 3.49 |
| 1.16.0 | SQFastScan（QT_8bit） | 1.17 / 1.08 / 0.99 | 1.42 / 1.37 / 1.07 |

### HNSW（M=32, efConstruction=200、検索 1 スレッド）

`plain` は `add()` だけ。`samples0` は 1.16.0 で `level_0_link_samples_per_node=0` にしてから `add()`。`sample_links` は `add()` の後に `add_level_0_links_from_sample(xt)`（サンプル 1 万件）を明示的に呼んだもの。

| 版 | モード | 構築秒（1 回目 / 2 回目） | ef=16 | ef=32 | ef=64 | ef=128 |
| --- | --- | --: | --: | --: | --: | --: |
| 1.15.1 | plain | 34.4 / 32.8 | 0.9038 | 0.9590 | 0.9838 | 0.9960 |
| 1.16.0 | plain | 32.1 / 32.6 | 0.9038 | 0.9590 | 0.9838 | 0.9960 |
| 1.16.0 | samples0 | 32.4 / 31.8 | 0.9038 | 0.9590 | 0.9838 | 0.9960 |
| 1.16.0 | sample_links | 36.0 / 34.6 | 0.9039 | 0.9590 | 0.9838 | 0.9960 |

（数値は recall@10。QPS は全モードで ef=16 が 9,940〜12,164、ef=128 が 2,011〜2,412 の範囲に入り、同じモードの 1 回目と 2 回目で最大 18% ずれた。表は `results/summary.md`）

`add_level_0_links_from_sample(xt)` の統計（1.16.0）: シンク 133 個を検出、リンクを 148 本追加・5 本置換、1 ラウンドで残りシンク 0、所要 3.8 秒（構築時間の約 12%）。

### IVF4096 + HNSW 粗量子化器（量子化器 efSearch=8、検索 1 スレッド、各 1 回）

| 版 | samples_per_node | 重心割り当ての正答率 | 最大リスト長 | 偏り係数 | nprobe=4 | nprobe=16 | nprobe=64 |
| --- | --: | --: | --: | --: | --: | --: | --: |
| 1.15.1 | — | 0.8826 | 449 | 2.0696 | 0.6536 | 0.7496 | 0.7921 |
| 1.16.0 | 3（既定） | 0.8830 | 449 | 2.0688 | 0.6538 | 0.7498 | 0.7923 |
| 1.16.0 | 0 | 0.8826 | 449 | 2.0696 | 0.6536 | 0.7496 | 0.7921 |

（nprobe 列は recall@10。重心割り当ての正答率は、HNSW 量子化器の割り当てが総当たりで最も近い重心と一致した割合）

## 考察

**SQ8 の高速化は本物で、公称の内容（x86 の 8bit 内積）どおり。** バッチでも 1 クエリずつでも約 2.1 倍で、recall は 1 桁目まで同じ（0.9735）。1.15.1 の SQ8 は単発の p95 が 10 ms 台に跳ねる回があったが、1.16.0 は 3〜4 ms に収まった。SQ8 で総当たりしている構成は、版を上げるだけで得をする。

**予想と違ったこと 1: バッチ検索では SQ8 が Flat より遅い。** 1,000 クエリを 1 バッチで投げると、`IndexFlatIP` は行列積（BLAS）の経路に乗るので、1.16.0 でも Flat 約 415 QPS に対して SQ8 は約 330 QPS だった。1 クエリずつ投げると逆転して、Flat 13 ms に対して SQ8 3 ms（4.4 倍速い）。RAG の API のように 1 リクエスト 1 クエリで検索するなら SQ8 が速く、評価用にクエリをまとめて流すと Flat の方が速く見える。**ベンチマークをバッチで取ると、本番の単発検索と逆の結論になりうる。**

**`IndexSQFastScan` は「メモリそのまま・ほぼ同じ精度で 4 倍速」の選択肢になる。** 既定の rerank_factor=2 で SQ8 に対して recall@10 −0.51pt、QPS 約 4 倍、単発 p50 は 1.08 ms（Flat の約 12 分の 1）。索引サイズが SQ8 と同じ 38.4 MB なのは、8bit コードを上位 4bit（走査用）と下位 4bit（再ランク用）に分けて持つ形（#5662 の split-nibble）だからだと読める（コードを読んで確かめてはいない）。rerank_factor=1（再ランクほぼなし）にすると recall が 0.8594 まで落ちるので、既定の 2 を下げる意味はない。4・8 に上げても +0.2〜0.3pt しか戻らず、SQ8 の 0.9735 には届かなかった。

**予想と違ったこと 2: シンク除去リンクは単体の HNSW では自動で入らない。** 1.16.0 の `IndexHNSWFlat` には `level_0_link_samples_per_node`（既定 3）という属性が増えているが、0 にしても既定のままでも `add()` の結果は recall が小数第 4 位まで同じだった。docstring には「HNSW を IVF の粗量子化器にしたとき、小さい efSearch だとリストが偏る。そのための対策で、`IndexIVF::train` から自動で呼ばれる」とある。リリースノートの「HNSW level-0 links」は HNSW 単体の改善ではなく、IVF の粗量子化器向けの変更だった。明示的に `add_level_0_links_from_sample(xt)` を呼ぶとシンクを 133 個見つけてリンクを 148 本足したが、10 万ノード中の 133 個なので recall@10 は +0.0001 しか動かなかった。

**IVF の粗量子化器でも、この規模では効果が誤差程度。** 重心 4,096 個・量子化器 efSearch=8 で、割り当て正答率 0.8826 → 0.8830、recall は +0.0002、リスト長の分布は同じだった。リリースノートが想定しているのは、重心が数万〜数百万ある IVF だと考えられる。1.16.0 の既定（3）の方が QPS が 12〜21% 高く出たが、1 回しか測っておらず、HNSW 単体の QPS が同じ条件で最大 18% ずれたことを踏まえると、ばらつきと区別できない。

**どう使い分けるか（この環境での目安）**:

- 10 万件規模で、索引を 4 分の 1 にしつつ総当たりに近い精度が欲しい → 1.16.0 の `IndexSQFastScan(d, QT_8bit, METRIC_INNER_PRODUCT)`。単発 1 ms 前後
- recall を 0.97 台で揃えたい・既存の SQ8 を使っている → 1.16.0 に上げるだけで約 2 倍
- HNSW 単体を使っている → 1.16.0 に上げても recall は変わらない。シンク除去リンクに期待しない

## 未検証・残課題

- **ニューラル埋め込みでの結果は未検証。** HF Hub に届かず、TF-IDF + SVD のベクトルで測った。文埋め込み（例: 384 次元の MiniLM 系）では HNSW のシンクの数や SQ の量子化誤差が変わる可能性がある
- IVF の粗量子化器としてのシンク除去リンクの効果は、重心 4,096 個でしか見ていない。数万〜数十万の重心（数百万〜数億件の索引）での効果は未検証
- IVF の QPS の差（1.16.0 既定が 12〜21% 速い）は 1 回の計測で、ばらつきか本当の差か未確定
- `IndexIVFSQFastScan`、RaBitQ 系の高速化（#5647 など）、`IndexPiPNN` は測っていない
- 2 vCPU の VM なので、スレッド数を増やしたときの伸びは未検証。AVX-512 のない CPU（#5829 の AVX2 経路だけ）での伸び方も未検証
- 索引サイズは `faiss.serialize_index` のバイト数で、プロセスの RSS は測っていない

## 参考リンク

- [faiss v1.16.0 リリースノート](https://github.com/facebookresearch/faiss/releases/tag/v1.16.0)
- [#5705 Add HNSW level-0 links from a sample to remove search sinks](https://github.com/facebookresearch/faiss/pull/5705)
- [#5789 Use 3 sample vectors per node by default for HNSW level-0 links](https://github.com/facebookresearch/faiss/pull/5789)
- [#5829 Speed up the x86 8-bit scalar quantizer inner-product distance](https://github.com/facebookresearch/faiss/pull/5829)
- [#5341 Add fast scan variants of SQ indexes - IndexSQFastScan and IndexIVFSQFastScan](https://github.com/facebookresearch/faiss/pull/5341)
- [#5662 Halve IndexSQFastScan rerank memory with a split-nibble layout](https://github.com/facebookresearch/faiss/pull/5662)
