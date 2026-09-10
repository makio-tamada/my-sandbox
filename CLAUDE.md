# CLAUDE.md

このリポジトリで作業するときに最初に読む文書です。

## このリポジトリ

`my-sandbox` は気になった技術を検証するための個人サンドボックスです。プロダクションコードではありません。
主な対象は Python（データ / ML / API）と LLM・Claude API・エージェントです。

検証 1 件は次の 3 つで構成されます。番号 `NNNN` と slug は 3 つすべてで一致させます。

| 何を | どこに |
| --- | --- |
| 検証コード（動かすためのもの） | `experiments/NNNN-slug/` |
| 成果レポート（読み返すためのもの） | `reports/NNNN-slug.md` |
| 作業ブランチ | `exp/NNNN-slug` |

## 必ず守ること

1. **Issue のない検証を始めない。** 対応する Issue を確認し、なければ作成してから着手する
2. **`main` に直接コミットしない。** 必ずブランチを切り、Pull Request 経由にする（命名は後述）
3. **PR には必ず `Closes #<Issue番号>` を書く。** マージで Issue がクローズされる状態にする
4. **PR をマージしない。** マージは人間が判断する（`gh pr merge` は使わない）
5. **検証は `experiments/NNNN-slug/` の中に閉じる。** リポジトリ直下や他の検証を汚さない
6. **実行していない結果を書かない。** 数値・エラー・所要時間は実際に実行して得たものだけを書き、
   確かめていない項目は「未検証」と明記する
7. **Python の依存は `pip` ではなく `uv` で入れる。** 単発は `uv run`（PEP 723）、規模が出たら `uv init` + `pyproject.toml`
8. **`.env` や API キーを読み出さない。** 出力・レポート・コミットに混ぜない

## ブランチ命名規則

`1 Issue = 1 ブランチ = 1 PR` を崩さないための規則です。

| 用途 | 書式 | 例 |
| --- | --- | --- |
| **技術検証**（メイン） | `exp/<NNNN>-<slug>` | `exp/0003-polars-vs-duckdb` |
| テンプレート・設定・土台の整備 | `chore/<Issue番号>-<slug>` | `chore/12-add-ts-template` |
| 既存の検証コードの修正 | `fix/<NNNN>-<slug>` | `fix/0003-wrong-benchmark-loop` |
| スキル・コマンド等の機能追加 | `feat/<Issue番号>-<slug>` | `feat/15-add-profiling-skill` |
| レポート・ドキュメントのみの修正 | `docs/<Issue番号>-<slug>` | `docs/18-fix-report-index` |

番号の使い分けには理由があります。検証系（`exp/` `fix/`）は 4 桁の**検証番号**を使い、ブランチ名から
`experiments/NNNN-slug/` と `reports/NNNN-slug.md` の両方が辿れるようにします。成果物ディレクトリを持たない
作業は対応する **Issue 番号**を使います。接頭辞は `exp` を除きコミット規約の type と揃えます。

slug の規則:

- 英小文字・数字・ハイフンのみ。日本語、アンダースコア、大文字、連続ハイフンは使わない
- 2〜5 語程度。ブランチ名全体で 50 文字以内を目安にする
- テーマを表す名詞句にする（`test`、`tmp`、`work`、`update` のような中身のない語を単独で使わない）
- 検証系の slug は `experiments/NNNN-<slug>/` および `reports/NNNN-<slug>.md` と完全一致させる

運用ルール:

- `main` では作業しない。`main` へ直接 push しない
- ブランチは対応する Issue が確定してから切る
- 1 ブランチに複数の検証を混ぜない。別テーマは別 Issue・別ブランチにする
- push は `git push -u origin <ブランチ名>`。マージ済みブランチの削除はマージする人間に任せる

## 言語とコミット規約

- 応答・ドキュメント・コメントは日本語で書く
- 変数・関数は英語 `snake_case`、クラスは英語 `PascalCase`
- コミットは日本語 Conventional Commits: `<type>: <日本語の要約>`
  （type は `feat` / `fix` / `docs` / `style` / `refactor` / `test` / `chore`）
  - 例: `feat: 0003 Polars と DuckDB の集計速度を比較`

## Claude API を扱うとき

**モデル ID を記憶で書かない。** `claude-api` スキルを読んでから書くこと。
現行のモデル ID は `claude-opus-5` / `claude-sonnet-5` / `claude-haiku-4-5-20251001` / `claude-fable-5-1` です。
API キーは `.env` の `ANTHROPIC_API_KEY` を環境変数経由で参照し、値そのものをファイルや出力に書かないこと。

## スラッシュコマンド

| コマンド | 内容 |
| --- | --- |
| `/new-exp <テーマ>` | Issue を作成し、ブランチを切り、検証ディレクトリの雛形を用意する |
| `/wrap-exp` | レポートを書き、索引を更新し、PR を作成する（マージはしない） |
| `/verify [ディレクトリ]` | ruff / mypy / pytest をまとめて実行する |

定義は `.claude/commands/` にあります。

## スキル

| スキル | いつ使うか |
| --- | --- |
| `experiment-workflow` | 検証を始める・進める・締めるとき（全体手順） |
| `experiment-report` | `reports/` にレポートを書くとき |
| `benchmark` | 速度・メモリ・精度を計測して比較するとき |
| `llm-experiment` | Claude API やエージェントを検証するとき |
| `python-env` | Python の検証環境を用意するとき |

定義は `.claude/skills/` にあります。

## ディレクトリ構成

```text
my-sandbox/
├── CLAUDE.md              # この文書
├── .claude/               # commands / skills / settings
├── .github/               # Issue / PR テンプレート
├── templates/             # 検証の雛形とレポートの雛形
├── experiments/           # 検証コード（NNNN-slug/）
└── reports/               # 成果レポート（NNNN-slug.md）と索引
```
