# 0006: pydantic 2.14.4 で model_validate_json のメモリ回帰が解消したか実測する

<!-- ここには動かし方だけを書く。結果と考察は reports/0006-pydantic-json-memory-regression.md に書く -->

## 動かし方

```shell
uv run main.py > results/summary.md   # 2 コアの VM で約 1 分
```

`main.py` は次を行う（Linux 専用。`/proc/self/clear_refs` と `/proc/self/status` を使う）。

1. `.venvs/<版>/` に pydantic 2.14.1 / 2.14.2 / 2.14.3 / 2.14.4 の仮想環境を uv で作る（Python 3.14）
2. pydantic#14234 の再現コードと同じ形の JSON（10 万件 × 属性 30、約 47 MB）を `.venvs/payload.json` に書く
3. `measure.py` を版 × モード（`root_dict` / `typed` / `from_json`）ごとに別プロセスで 5 回ずつ実行する
4. 表を標準出力に、生データを `results/raw.json` に保存する

オプション: `--runs`（既定 5）、`--n-obj`（既定 100000）、`--n-attrs`（既定 30）。

補助スクリプト（`main.py` の実行後に、版ごとの python で直接叩く）:

```shell
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python repro_issue14234.py; done
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python inspect_python_heap.py --payload .venvs/payload.json; done
for v in 2.14.1 2.14.2 2.14.3 2.14.4; do .venvs/$v/bin/python inspect_strings.py --payload .venvs/payload.json; done
```

| スクリプト | 内容 |
| --- | --- |
| `repro_issue14234.py` | pydantic#14234 の再現コードそのまま |
| `inspect_python_heap.py` | 結果の Python オブジェクトの量（tracemalloc と `sys.getsizeof`） |
| `inspect_strings.py` | 同じ内容の文字列が何個の別オブジェクトになっているか |
