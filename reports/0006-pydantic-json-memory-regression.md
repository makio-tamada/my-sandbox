# 0006: pydantic 2.14.4 で model_validate_json のメモリ回帰が解消したか実測する

**結論**: 47 MB の JSON を `model_validate_json` すると、2.14.2 / 2.14.3 は 2.14.1 よりピーク RSS が 86 MB（15〜19%）多かったが、2.14.4 では回帰が消え、2.14.1 よりさらに 70 MB 少なくなった。差は Python オブジェクトの量ではなく、malloc_trim で返せる領域にある

| 項目 | 値 |
| --- | --- |
| Issue | #15 |
| PR | #16 |
| 実施日 | 2026-11-21 |
| 種別 | python-script |
| 状態 | ✅ 完了 |
| コード | [experiments/0006-pydantic-json-memory-regression/](../experiments/0006-pydantic-json-memory-regression/) |

## 何を確かめたかったか

pydantic v2.14.4（2026-11-19 公開）のリリースノートには「jiter を v0.19.0 に上げ、前回の jiter 更新で入ったメモリの問題に対処した」（#14247）とある。
元の報告 pydantic#14234 では、47 MB の JSON を `RootModel[dict[str, object]]` に `model_validate_json` で読ませたとき、RSS の増分が 2.14.1 の 356 MB から 2.14.2 / 2.14.3 で 443 MB に増えた（約 +25%）。

大きな JSON をモデルで読む処理はよくあるので、次を手元で確かめたかった。

1. 回帰を再現できるか。2.14.4 で本当に戻るか
2. 増えているのは「ピーク」か「処理後も残る量」か
3. 型付きモデルや `pydantic_core.from_json` でも同じか。処理時間は変わるか

仮説は「2.14.2 / 2.14.3 で +20〜25% を再現でき、2.14.4 で 2.14.1 とほぼ同じに戻る。増加分は一時確保で、処理後に残る量は版で大差ない」。

## 前提・計測環境

| 項目 | 内容 |
| --- | --- |
| マシン | クラウドの Linux VM（Intel Xeon @ 2.30GHz、2 vCPU、メモリ 7 GiB、カーネル 6.18、glibc の malloc） |
| Python | 3.14.6（uv 配布のビルド） |
| 主要ライブラリ | pydantic 2.14.1（pydantic-core 2.50.1）/ 2.14.2（2.50.2）/ 2.14.3（2.50.4）/ 2.14.4（2.50.5）。版ごとに別の仮想環境。2.14.4 の環境の依存は typing-extensions 4.16.0、annotated-types 0.8.0、typing-inspection 0.4.5 |
| データ規模 | pydantic#14234 と同じ形の JSON。10 万件 × 属性 30（`{"items": [{"id": ..., "kind": {...}, "attributes": {"key0": "", ...}}]}`）、47.1 MB |
| 試行回数 | 版 × モードごとに別プロセスで 5 回（版を交互に実行）、中央値。再現コードは 4 版 × 3 回 |

読み方（モード）は 3 通り。

| モード | 内容 |
| --- | --- |
| `root_dict` | `RootModel[dict[str, object]].model_validate_json`（元の報告と同じ） |
| `typed` | `items: list[Item]`（`Item` は `id: str`、`kind: Kind`、`attributes: dict[str, str]`）の `model_validate_json` |
| `from_json` | `pydantic_core.from_json`（モデルを通さず dict に） |

計測した量（すべて JSON をファイルから bytes で読んだ直後の RSS からの増分）:

- **ピーク RSS**: 計測直前に `/proc/self/clear_refs` に `5` を書いて VmHWM を戻し、パース後の VmHWM を読む
- **ru_maxrss の増分**: 元の報告と同じ取り方（プロセス開始以来のピークどうしの差）
- **結果保持中 / 結果を捨てた後 / さらに `malloc_trim(0)` 後**: その時点の RSS（`/proc/self/statm`）

## 手順（再現方法）

```shell
cd experiments/0006-pydantic-json-memory-regression
uv run main.py > results/summary.md
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python repro_issue14234.py; done          # 3 回繰り返した
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python inspect_python_heap.py --payload .venvs/payload.json; done
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python inspect_strings.py --payload .venvs/payload.json; done
```

`main.py` は 47 MB の JSON で 2 回実行した（ほかに 2 万件の小さい JSON で動作確認を 1 回）。2 回目で `malloc_trim` 後の計測を足した。下の表は 2 回目で、1 回目もピーク RSS と結果保持中の値は 1 MB 以内で同じだった。

## 結果

### `root_dict`（元の報告と同じ読み方、5 回の中央値。括弧内は最小〜最大）

| 指標 | 2.14.1 | 2.14.2 | 2.14.3 | 2.14.4 |
| --- | ---: | ---: | ---: | ---: |
| ピーク RSS 増分 (MB) | 574 (574〜574) | 660 (660〜660) | 659 (659〜659) | 504 (504〜504) |
| ru_maxrss の増分 (MB) | 285 (285〜285) | 370 (370〜370) | 370 (369〜370) | 215 (215〜215) |
| 結果保持中の RSS 増分 (MB) | 574 | 660 | 659 | 504 |
| 結果を捨てて gc した後 (MB) | 355 | 441 | 440 | 285 |
| さらに `malloc_trim(0)` 後 (MB) | 2 | 2 | 2 | 2 |
| 処理時間 (秒) | 0.52 (0.47〜0.59) | 0.64 (0.55〜0.67) | 0.65 (0.58〜0.69) | 0.52 (0.51〜0.62) |

### `typed`

| 指標 | 2.14.1 | 2.14.2 | 2.14.3 | 2.14.4 |
| --- | ---: | ---: | ---: | ---: |
| ピーク RSS 増分 (MB) | 465 (465〜465) | 551 (551〜551) | 550 (550〜554) | 395 (395〜395) |
| 結果を捨てて gc した後 (MB) | 465 | 551 | 550 | 395 |
| さらに `malloc_trim(0)` 後 (MB) | 111 | 111 | 111 | 111 |
| 処理時間 (秒) | 0.52 (0.52〜0.53) | 0.61 (0.58〜0.62) | 0.59 (0.59〜0.65) | 0.55 (0.54〜0.56) |

### `from_json`

| 指標 | 2.14.1 | 2.14.2 | 2.14.3 | 2.14.4 |
| --- | ---: | ---: | ---: | ---: |
| ピーク RSS 増分 (MB) | 126 (126〜126) | 126 (126〜140) | 126 (126〜126) | 126 (126〜126) |
| さらに `malloc_trim(0)` 後 (MB) | 50 | 50 | 49 | 49 |
| 処理時間 (秒) | 0.25 (0.24〜0.26) | 0.29 (0.29〜0.33) | 0.29 (0.29〜0.31) | 0.29 (0.28〜0.31) |

ピーク RSS の版間の差（`root_dict` / `typed` 共通）: 2.14.1 → 2.14.2 で **+86 MB**（`root_dict` +15.0%、`typed` +18.5%）、2.14.1 → 2.14.4 で **−70 MB**（−12.2% / −15.1%）。

### 元の報告の再現コード（`repro_issue14234.py`、3 回とも同じ値）

| 版 | 元の報告 | 手元 |
| --- | ---: | ---: |
| 2.14.1 | 356 MB | 357 MB |
| 2.14.2 | 443 MB | 442 MB |
| 2.14.3 | 443 MB | 442 MB |
| 2.14.4 | （報告なし） | 287 MB |

### 切り分け（`root_dict` の結果について、4 版とも同じ値）

- tracemalloc で測った Python 側の確保量: 現在 295.9 MB、ピーク 295.9 MB
- 結果のオブジェクトの `sys.getsizeof` の合計: 262.7 MB（dict 1 個 832 バイト、キー文字列 1 個 45 バイトなど、すべて同じ）
- 属性のキー（`"key0"`〜`"key29"`）は 4 版とも 300 万個の別オブジェクトとして作られていた（同じ文字列の共有はなし）。値の `""` は 1 個を共有
- 参考: `from_json` の結果ではキーがキャッシュで共有されており、別オブジェクトの数は 2.14.1 で 206 個、2.14.2 で 148,104 個、2.14.3 で 179 個、2.14.4 で 299,327 個と版ごとに違った（各 1 回）

## 考察

**回帰は再現でき、2.14.4 で解消した。** 元の報告の再現コードは 1 MB 単位でほぼ同じ数値になり、2.14.2 / 2.14.3 の増加（+86 MB）は環境によらない現象とみてよい。
2.14.4 は 2.14.1 の水準に戻っただけでなく、さらに 70 MB（約 12〜15%）少なくなった。リリースノートの「対処した」以上の改善になっている。
処理時間も `root_dict` は 2.14.2 / 2.14.3 で約 2 割遅くなり、2.14.4 で 2.14.1 と同じに戻った。

**増えていたのは Python オブジェクトではない。** Python 側の確保量（tracemalloc）も、作られるオブジェクトの大きさと数も 4 版でまったく同じだった。
それでも RSS は版で ±80 MB 前後動き、`malloc_trim(0)` を呼ぶと 4 版とも同じ値（`root_dict` は 2 MB）まで下がる。
つまり差は「pydantic-core（Rust 側）がパース中に glibc の malloc から確保して解放したが、OS に返されずに残っている領域」の大きさで、リークではない。
jiter 0.19.0 で一時確保の量か確保の仕方が変わったためと推測するが、jiter のソースや変更履歴は読んでいないので未確認。
仮説の「処理後に残る量は版で大差ない」は外れで、`gc.collect()` だけでは版間の差がそのまま残った（`root_dict` で 355 / 441 / 440 / 285 MB）。

**`from_json` は影響を受けていない。** ピーク RSS は 4 版とも 126 MB で、回帰は `model_validate_json` の経路だけに出た。
一方で `from_json` の処理時間は 2.14.2 以降 0.25 秒 → 0.29 秒（約 16%）遅くなったままで、2.14.4 でも戻っていない（2 回の `main.py` 実行で同じ傾向、5 回ずつの範囲も重ならない）。

**実務で効く場面。** 大きな JSON を `model_validate_json` で一度に読むバッチ処理では、2.14.2 / 2.14.3 を使っているなら 2.14.4 に上げるだけでピークが約 2 割下がる（660 → 504 MB）。
長く動くプロセスで RSS が下がらないのが気になる場合、版によらず `malloc_trim(0)` で大半を OS に返せることも分かった（glibc を使う Linux の場合）。

## 未検証・残課題

- jiter 0.19.0 の何が効いたのか（変更履歴・ソース）は読んでおらず、原因は推測にとどまる
- macOS、musl（Alpine）、mimalloc などほかのメモリアロケータ、free-threaded ビルドでは未検証
- `from_json` の処理時間の悪化（約 16%）が何に由来するか、上流で既知かは未確認
- `typed` で `malloc_trim` 後も 111 MB 残る理由（4 版共通）は調べていない
- JSON の形（深いネスト、長い文字列、数値の多いデータ）やサイズを変えた計測は未検証。今回は元の報告と同じ形の 1 種類だけ
- `from_json` のキー文字列の共有数が版ごとに大きく違う理由と、それが速度に関係するかは未検証

## 参考リンク

- [pydantic v2.14.4 リリースノート（2026-11-19）](https://github.com/pydantic/pydantic/releases/tag/v2.14.4)
- [pydantic#14247: Bump jiter to v0.19.0](https://github.com/pydantic/pydantic/pull/14247)
- [pydantic#14234: model_validate_json retains ~25% more memory than 2.50.1 for large JSON payloads](https://github.com/pydantic/pydantic/issues/14234)
- [proc(5): /proc/pid/clear_refs](https://man7.org/linux/man-pages/man5/proc_pid_clear_refs.5.html)
