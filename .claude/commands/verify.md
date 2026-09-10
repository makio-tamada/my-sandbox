---
description: 検証ディレクトリの ruff / mypy / pytest をまとめて実行する
---

指定された検証ディレクトリで品質チェックを実行してください。

対象: $ARGUMENTS （省略時は現在のブランチに対応する `experiments/NNNN-slug/`）

対象ディレクトリで以下を順に実行します。**途中で失敗しても残りを実行し、失敗したものをすべて挙げてください。**

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy .        # mypy の設定がある場合のみ
uv run pytest        # tests/ がある場合のみ
```

注意点:

- `python-script` 種別（PEP 723 の単発スクリプト）には `pyproject.toml` がないため、
  `uv run --script main.py` が完走することの確認に読み替える
- 設定やテストが存在しない項目は「対象なし」として報告し、失敗として扱わない
- ここは検証用リポジトリなので、`ruff` の指摘は修正するが、型の厳格さは求めない。
  ただし**実行して動くことは必ず確認する**

すべて通った場合は、その旨を 1 行で報告してください。
