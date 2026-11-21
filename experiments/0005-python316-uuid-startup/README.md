# 0005: Python 3.16.0a2 の uuid C 実装と起動高速化を 3.15 と実測比較

<!-- ここには動かし方だけを書く。結果と考察は reports/0005-python316-uuid-startup.md に書く -->

## 動かし方

比較する 2 つのインタプリタを uv で入れてから、まとめ役の `main.py` を実行する。
標準ライブラリだけで動く（追加の依存なし）。

```shell
uv python install 3.15.2 3.16.0a2   # 古い uv だと 3.16.0a2 が見つからない。そのときは uvx uv python install ...
uv run main.py > results/summary.md
```

`main.py` は次の 3 本を順に呼び、表を標準出力に、生データを `results/*.json` に保存する（2 コアの VM で約 1 分半）。

| スクリプト | 内容 | 単体での実行例 |
| --- | --- | --- |
| `bench_uuid.py` | uuid4 / uuid7 / `UUID(str)` / `UUID(bytes=)` / `str(UUID)` の 1 回あたり時間と正しさ | `python3.16 bench_uuid.py --pure` |
| `check_compat.py` | pickle・copy・hash・fork など互換性の確認（項目ごとに子プロセス） | `python3 check_compat.py <py3.15> <py3.16>` |
| `bench_startup.py` | `python -c pass` などの起動時間（交互に 200 回） | `python3 bench_startup.py <py3.15> <py3.16>` |

`bench_uuid.py --pure` は `import uuid` の前に `sys.modules["_uuid"] = None` を入れて、純 Python のフォールバックを使わせる。
