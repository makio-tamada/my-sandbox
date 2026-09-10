# NNNN: <テーマ>

<!-- ここには動かし方だけを書く。結果と考察は reports/NNNN-slug.md に書く -->

## 動かし方

```shell
uv sync
uv run python -c "from src.experiment import run; print(run())"
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

`/verify experiments/NNNN-slug` でまとめて実行できます。
