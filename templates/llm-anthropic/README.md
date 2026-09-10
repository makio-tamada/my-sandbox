# NNNN: <テーマ>

<!-- ここには動かし方だけを書く。結果と考察は reports/NNNN-slug.md に書く -->

## 準備

リポジトリ直下の `.env.example` を `.env` にコピーし、`ANTHROPIC_API_KEY` を設定します。
`.env` はコミットされません。

## 動かし方

```shell
uv run main.py        # Messages API の最小呼び出し
uv run tool_use.py    # ツール定義とエージェントループ
```

## ファイル

| ファイル | 役割 |
| --- | --- |
| `config.py` | モデル ID とパラメータ。比較検証ではここだけ差し替える |
| `client.py` | `.env` の読み込みとクライアント生成 |
| `main.py` | Messages API の最小呼び出し。3 回試行してトークン数を出す |
| `tool_use.py` | `@beta_tool` + `tool_runner` によるツール呼び出し |
| `runs/` | 実行ごとのレスポンス（`.gitignore` 対象外にしたい場合は個別に判断） |

## 検証するときの注意

- **モデル ID を記憶で書かない。** `claude-api` スキルで現行の ID と料金を確認する
- **1 回の出力を結論にしない。** 最低 3 回試し、揺らぎの幅を記録する
- レポートにはモデル ID・`max_tokens`・`effort`・試行回数・入出力トークン数・概算コストを残す

詳しい作法は `$llm-experiment` スキルを参照してください。
