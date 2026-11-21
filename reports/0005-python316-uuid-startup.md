# 0005: Python 3.16.0a2 の uuid C 実装と起動高速化を 3.15 と実測比較

**結論**: 3.16.0a2 の C 実装で uuid4 は 3.15.2 比 4.4〜4.6 倍、uuid7 は 6.9〜7.2 倍速くなった（公称の 15 倍・30 倍には届かない）が、`is_safe` を渡さずに作った UUID を pickle / `copy` するとインタプリタがセグメンテーション違反で落ちる。起動時間は約 4%（0.4〜1 ms）短縮

| 項目 | 値 |
| --- | --- |
| Issue | #13 |
| PR | （作成後に追記） |
| 実施日 | 2026-11-21 |
| 種別 | python-script |
| 状態 | ✅ 完了 |
| コード | [experiments/0005-python316-uuid-startup/](../experiments/0005-python316-uuid-startup/) |

## 何を確かめたかったか

2026-11-10 に公開された Python 3.16.0a2 のアナウンスと What's New は、次の 2 点を挙げている。

1. `uuid.uuid4()` / `uuid.uuid7()` / `uuid.UUID` が C 実装になった（gh-139123）。マイクロベンチマークで、純 Python 実装に対して uuid4 生成 15.01 倍、uuid7 生成 29.64 倍、`UUID(str)` 6.76 倍、`UUID(bytes=)` 5.16 倍、`str(UUID)` 6.66 倍
2. インタプリタの起動が速くなった（gh-159137 ほか）

公称値は「C 実装 vs 純 Python 実装」の比較なので、利用者が体感する「3.15 から上げたらどれだけ変わるか」とは分母が違う。
手元の同じマシン・同じビルド条件で 3.15.2 と 3.16.0a2 を並べ、倍率と、実装の置き換えで挙動が変わっていないかを確かめた。

仮説は「C 実装同士の比較なら公称値に近い。ただし uuid4 は `os.urandom` が下限になって 15 倍には届かない。起動時間の改善は数 % 程度」。

## 前提・計測環境

| 項目 | 内容 |
| --- | --- |
| マシン | クラウドの Linux VM（Intel Xeon @ 2.30GHz、2 vCPU、メモリ 7 GiB、カーネル 6.18） |
| Python | 3.15.2 と 3.16.0a2。どちらも uv が配布する python-build-standalone のビルド（2026-11-11 ビルド、Clang 23.1.3、PGO + LTO、GIL あり）。3.16.0a2 の入手には uv 0.13.9（`uvx uv`）を使った。手元の uv 0.11.32 の一覧には 3.16.0a2 がなかった |
| 主要ライブラリ | 標準ライブラリのみ（`uuid`、`pickle`、`copy`、`timeit`、`subprocess`） |
| 比較対象 | ① 3.15.2（純 Python 実装）② 3.16.0a2 の既定（C 実装）③ 3.16.0a2 で `sys.modules["_uuid"] = None` にして純 Python フォールバックを使わせたもの |
| データ規模 | 正しさの確認は uuid4・uuid7 を各 100 万件生成。fork の確認は親子で各 10 万件 |
| 試行回数 | uuid は `timeit` の `autorange()` で決めた回数 × 2 を 7 回繰り返し、1 回あたり時間の中央値。起動時間は 2 つのインタプリタを交互に 200 回ずつ起動（ウォームアップ 10 回）。`main.py` 全体を 3 回実行し、下の表は 3 回目、倍率の幅は 3 回分 |

## 手順（再現方法）

```shell
cd experiments/0005-python316-uuid-startup
uvx uv python install 3.15.2 3.16.0a2
uv run main.py > results/summary.md   # 約 1 分半。生データは results/*.json
```

原因の調査で個別に叩いたコマンド（3.16.0a2）:

```shell
python3.16 -X faulthandler -c "import uuid; uuid.uuid4().__reduce__()"
python3.16 -c "import uuid; print(uuid.UUID('6f2c1e0a-3b4d-4c5e-8f60-718293a4b5c6', is_safe=uuid.SafeUUID.unknown).__getstate__())"
python3.16 -m timeit -s "import os" "os.urandom(16)"
```

## 結果

### uuid 1 回あたりの時間（ns、7 回の中央値。括弧内は最小〜最大。3 回目の実行）

| 操作 | ① 3.15.2 | ② 3.16.0a2 C | ③ 3.16.0a2 純Python | ③ / ②（公称値の比較） | ① / ②（3.15 からの改善） |
| --- | ---: | ---: | ---: | ---: | ---: |
| `uuid4()` | 711 (702〜725) | 160 (158〜162) | 730 (710〜770) | 4.56x | 4.44x |
| `uuid7()` | 1136 (1122〜1186) | 158 (158〜162) | 1074 (1057〜1202) | 6.79x | 7.18x |
| `UUID(str)` | 544 (530〜568) | 96 (96〜97) | 539 (523〜606) | 5.60x | 5.64x |
| `UUID(bytes=)` | 410 (406〜411) | 63 (63〜64) | 418 (410〜484) | 6.62x | 6.49x |
| `str(UUID)` | 274 (269〜309) | 34 (33〜34) | 264 (256〜310) | 7.83x | 8.12x |

3 回の実行での倍率の幅（① / ②）: uuid4 4.41〜4.61x、uuid7 6.89〜7.18x、`UUID(str)` 5.64〜5.72x、`UUID(bytes=)` 6.37〜6.51x、`str(UUID)` 8.12〜8.70x。

公称値との対比（③ / ②、3 回の幅）:

| 操作 | 公称値 | 実測 |
| --- | ---: | ---: |
| `uuid4()` | 15.01x | 4.38〜4.58x |
| `uuid7()` | 29.64x | 6.79〜7.11x |
| `UUID(str)` | 6.76x | 5.48〜5.70x |
| `UUID(bytes=)` | 5.16x | 6.62〜6.75x |
| `str(UUID)` | 6.66x | 7.83〜8.65x |

参考: 同じ VM で `os.urandom(16)` は 1 回 277 ns（`timeit` の best of 5、1 回だけ計測）。

### 正しさ（3 通りとも、3 回とも同じ）

- uuid4 100 万件: すべて version 4・RFC 4122 variant、重複なし
- uuid7 100 万件: すべて version 7、生成順に厳密に単調増加、重複なし
- `UUID(str(u)) == u`、`UUID(bytes=u.bytes) == u`（1 万件）: 成立
- C 版 `uuid.UUID` と純 Python 版 `uuid._py_UUID` を同じ文字列から作ると、`int`・`str`・`==` は一致、**`hash()` は不一致**

### 互換性（`check_compat.py`、項目ごとに別プロセス）

| 項目 | 3.15.2 | 3.16.0a2 |
| --- | --- | --- |
| pickle: `uuid4()` の往復 | True | **クラッシュ（SIGSEGV）** |
| pickle: `UUID(str)` の往復 | True | **クラッシュ（SIGSEGV）** |
| pickle: `UUID(str, is_safe=SafeUUID.unknown)` の往復 | True | True |
| pickle: `uuid1()` の往復 | True | True |
| `copy.deepcopy`: UUID を値に持つ dict | True | **クラッシュ（SIGSEGV）** |
| `copy.copy`: `uuid7()` | True | **クラッシュ（SIGSEGV）** |
| `hash(u) == hash(u.int)` | True | False |
| C 版と純 Python 版の同値オブジェクトを set に入れると 1 件 | True | False（2 件） |
| fork 後に親子の `uuid4()` が重複しない（各 10 万件） | True | True |

クラッシュの補足（3.16.0a2 で個別に確認）:

- `uuid.uuid4().__reduce__()` だけでも落ちる。faulthandler の出力は `copyreg.py` 95 行目の `_reduce_ex` から `PyDict_SetItem` で SIGSEGV
- `uuid.uuid4().__getstate__()` でも落ちる。`is_safe=` を明示して作った UUID と、`uuid1()` の結果は落ちない
- 3.15.2 で pickle したバイト列を 3.16.0a2 で `pickle.loads` するのは成功した
- `hash()` は C 版では別プロセスで値が変わった（同じ UUID で 2 回起動して 2 回とも異なる値）。3.15.2 は `hash(u.int)` と同じ値

### 起動時間（ms、200 回の中央値。括弧内は p10〜p90。3 回目の実行）

| コマンド | 3.15.2 | 3.16.0a2 | 差（3.16 − 3.15） |
| --- | ---: | ---: | ---: |
| `python -I -c pass` | 9.67 (9.26〜13.01) | 9.30 (8.92〜12.98) | −0.37 ms（−3.8%） |
| `python -c pass`（site あり） | 9.40 (9.24〜9.67) | 9.00 (8.84〜9.32) | −0.39 ms（−4.2%） |
| `python -I -c "import json, re, pathlib, dataclasses, typing, uuid"` | 22.99 (22.40〜26.84) | 21.96 (21.44〜25.83) | −1.03 ms（−4.5%） |

3 回の実行での差の幅: `-I -c pass` −0.37〜−0.38 ms（−3.7〜−4.3%）、site あり −0.39〜−0.42 ms（−4.1〜−4.3%）、6 モジュール import −0.89〜−1.03 ms（−4.0〜−4.5%）。
絶対値は実行ごとに 1 ms ほど上下したが、差の向きと大きさは 3 回とも同じだった。

## 考察

**速度について。** C 実装で速くなったこと自体は全操作で確認でき、3.15 からの改善幅（① / ②）は 4.4〜8.7 倍だった。
一方で生成系の倍率は公称値の 1/3〜1/4 にとどまった。この VM では `os.urandom(16)` だけで約 280 ns かかり、純 Python 版 uuid4（約 710 ns）の 4 割ほどを占める。
C 版の uuid4 は乱数をまとめて取ってキャッシュする（gh-160215 で言及されている entropy cache）ため、この差が効いているはず。
公称値との差は、計測環境（VM のシステムコールの重さ、CPU）の違いによる可能性が高いが、公称値の計測条件は確かめていない。
構築・文字列化（`UUID(bytes=)`、`str(UUID)`）は逆に公称値より大きな倍率が出た。
実務では、UUID を大量に生成・パースする処理（ログの ID 付与、DB への一括投入など）で効く。1 件あたり 0.5 µs 前後の差なので、100 万件で 0.5 秒程度の短縮になる計算。

**互換性について。これが今回いちばん重要な発見。** 3.16.0a2 の C 実装では、`is_safe` を指定せずに作った UUID（`uuid4()`・`uuid7()`・`UUID(str)` の通常の使い方すべて）を pickle・`copy.copy`・`copy.deepcopy` するとインタプリタごと落ちる。
例外ではなく SIGSEGV なので `try` では拾えない。`multiprocessing` でのプロセス間受け渡し、キャッシュへの保存、dataclass の `deepcopy` など、UUID を含むオブジェクトを複製・直列化する経路はすべて影響を受けると考えられる（それらの経路は個別には試していない）。

原因はソースで確認できた。v3.16.0a2 の `Modules/_uuidmodule.c` では、UUID オブジェクトの `is_safe` スロットが既定で `NULL` のまま（1031 行目）で、
プロパティ `is_safe` の getter は `NULL` なら `SafeUUID.unknown` を返す（1104〜1117 行目）のに、`__getstate__` は `self->is_safe` を確認せずに `PyDict_SetItem` に渡している（1624 行目）。
`is_safe=` を明示すると落ちないこと、`uuid1()`（内部で `is_safe` を設定する）が落ちないこととも辻褄が合う。
2026-11-21 時点の `main` ブランチの同じ関数も変わっていなかった。

`hash()` の不一致は、C 版がハッシュ値を独自に計算してキャッシュするためと見られる（gh-139123 に「faster hash() implementation」とある）。
C 版と純 Python 版のオブジェクトは `==` で等しいのに `hash()` が違うため、`a == b なら hash(a) == hash(b)` という約束が破れ、両方を set や dict に入れると重複して残る。
ただし純 Python 版は `uuid._py_UUID`（非公開名）でしか作れないので、通常のコードで両者が混ざる場面は少ない。
`hash(u) == hash(u.int)` に依存するコードは見たことがないが、3.15 までは成り立っていた性質なので記録しておく。

**起動時間について。** 約 4%（0.4〜1 ms）の短縮で、予想どおり「数 %」だった。CLI ツールを大量に起動する場面以外では体感できない大きさ。

**どう使うか。** 3.16 は 2027-10 の正式版まで変わりうるアルファ版なので、現時点で採用判断をする段階ではない。
ただし 3.16 で自分のコードを試すときは、UUID を pickle / copy する経路がないかを最初に確認する。回避策は `UUID(..., is_safe=uuid.SafeUUID.unknown)` で作り直すことだが、`uuid4()` の戻り値には使えないので、上流で直るのを待つのが現実的。

## 未検証・残課題

- **上流（python/cpython）への報告はしていない。** 簡単な検索では同じ症状の Issue は見つからなかったが、網羅的には確かめていない。報告するかどうかは人間が判断する
- python.org の公式ビルドやソースからのビルドでは試していない（python.org に接続できない環境だったため）。ソースの該当箇所は v3.16.0a2 タグで確認したので、ビルド固有の問題ではないと考えているが、実行での確認は未検証
- `multiprocessing`、`concurrent.futures`、`functools.cache` など、pickle / copy を内部で使う具体的なライブラリ経由での再現は未検証
- gh-160215（PID 名前空間をまたぐと uuid4 が重複しうる）の再現は未検証。通常の `fork` では重複しないことだけ確かめた
- 公称値（15 倍・30 倍）の計測条件（マシン、OS）は未確認。macOS や物理マシンでの計測は未検証
- What's New にある `ast.parse()` の高速化（約 16%）とメモリ削減（約 52%）、正規表現の集合演算は今回の対象外で未検証
- free-threaded ビルド、JIT 有効時の挙動は未検証

## 参考リンク

- [Python 3.16.0 alpha 2 is now available!（discuss.python.org, 2026-11-10）](https://discuss.python.org/t/python-3-16-0-alpha-2-is-now-available/110011)
- [What's new in Python 3.16](https://docs.python.org/3.16/whatsnew/3.16.html)
- [gh-139123: uuid の C 実装](https://github.com/python/cpython/issues/139123)
- [gh-160215: `uuid.uuid4()` can generate duplicates](https://github.com/python/cpython/issues/160215)
- [Modules/_uuidmodule.c（main）](https://github.com/python/cpython/blob/main/Modules/_uuidmodule.c)
