---
name: python-env
description: 検証用の Python 環境を uv で用意する。依存を追加する、仮想環境を作る、単発スクリプトを書く、pyproject を設定する、といったときに使用する。
---

# uv での環境構築

**`pip` は使わない。** このリポジトリの Python 環境はすべて `uv` で管理する。

## パッケージを取得できない環境

クラウドの自動実行など、PyPI に届かない環境では `uv run` の依存解決が失敗する
（`Failed to fetch: https://pypi.org/simple/...` や名前解決のエラー）。そのときは次のようにする。

1. 入っているライブラリを確認する

   ```shell
   python3 -c "import importlib.metadata as m; print(sorted(d.metadata['Name'] for d in m.distributions()))"
   ```

2. 必要なものが入っていれば `python3 main.py` で直接実行する。PEP 723 のメタデータは残してよい
3. 入っていなければ、テーマか手法を変える。インストールを何度も試さない
4. レポートの「前提・計測環境」に「パッケージ取得不可のため既存環境で実行」と、使ったライブラリのバージョンを書く

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
