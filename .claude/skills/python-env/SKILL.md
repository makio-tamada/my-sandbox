---
name: python-env
description: 検証用の Python 環境を uv で用意する。依存を追加する、仮想環境を作る、単発スクリプトを書く、pyproject を設定する、といったときに使用する。
---

# uv での環境構築

**`pip` は使わない。** このリポジトリの Python 環境はすべて `uv` で管理する。

## 種別の選び方

| 状況 | 種別 | 起点 |
| --- | --- | --- |
| 1 ファイルで済む。動けばいい | `python-script` | `templates/python-script/` |
| テストを書く。複数モジュールになる | `python-project` | `templates/python-project/` |
| Claude API を叩く | `llm-anthropic` | `templates/llm-anthropic/` |

迷ったら `python-script` から始める。育ったら `python-project` へ移す。

## 単発スクリプト（PEP 723）

依存をファイル冒頭のインラインメタデータに書けば、`uv run` が依存解決から実行までやる。
仮想環境を自分で作らない。

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["polars>=1.0", "duckdb>=1.0"]
# ///
```

```shell
cd experiments/NNNN-slug && uv run main.py
```

依存の追加は手で書くか `uv add --script main.py <package>`。

## プロジェクト形式

```shell
cd experiments/NNNN-slug
uv sync              # pyproject.toml から環境を作る
uv add <package>     # 依存を追加する（pyproject.toml と uv.lock が更新される）
uv run pytest        # 仮想環境を意識せず実行する
```

- **`uv.lock` はコミットする。** 後から同じ環境を再現するため
- `.venv/` はコミットしない（`.gitignore` 済み）
- Python は `mise.toml` で 3.12 に固定してある

## 品質チェック

`/verify <ディレクトリ>` で ruff / mypy / pytest をまとめて実行できる。
検証コードなので厳格さは求めないが、**動くことは確認してからレポートを書く**。
