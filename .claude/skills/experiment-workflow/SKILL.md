---
name: experiment-workflow
description: 技術検証を Issue から PR まで一貫して進める手順。新しい検証を始める、検証中の作業を進める、検証を締めて PR にする、番号やブランチ名やディレクトリ名を決める、といったときに使用する。
---

# 検証のライフサイクル

検証 1 件は `1 Issue = 1 ブランチ = 1 PR` で進める。番号 `NNNN` と slug は
ブランチ・ディレクトリ・レポートの 3 つで完全に一致させる。

## 1. Issue を確認する

対応する Issue がなければ、着手前に作成する。本文には最低限「確かめたいこと」と
「何が分かれば終わりか（完了条件）」を書く。

```shell
gh issue list --label experiment
gh issue create --title "[検証] <テーマ>" --body-file <path> --label experiment
```

## 2. 番号と slug を決める

```shell
ls experiments/   # 既存の最大番号 + 1 が今回の NNNN（4 桁ゼロ埋め）
```

slug は英小文字・数字・ハイフンのみ、2〜5 語、テーマを表す名詞句にする。
日本語・アンダースコア・大文字は使わない。`test` `tmp` `work` のような中身のない語を単独で使わない。

## 3. ブランチを切る

```shell
git switch -c exp/NNNN-slug
```

`main` では作業しない。ブランチ名の書式は `CLAUDE.md` の「ブランチ命名規則」に従う。
検証系（`exp/` `fix/`）は検証番号、それ以外（`chore/` `feat/` `docs/`）は Issue 番号を使う。

## 4. 雛形を置く

種別を選び `templates/` からコピーする。判断に迷ったら `$python-env` を読む。

| 種別 | 使いどころ | コピー元 |
| --- | --- | --- |
| `python-script` | 単発の確認。1 ファイルで済む | `templates/python-script/` |
| `python-project` | 腰を据える。テストを書く | `templates/python-project/` |
| `llm-anthropic` | Claude API / エージェント | `templates/llm-anthropic/` |

`experiments/NNNN-slug/README.md` には**動かし方だけ**を書く。考察や結果は書かない（レポート側の役割）。

## 5. 検証する

計測を伴うなら `$benchmark`、Claude API を叩くなら `$llm-experiment` の作法に従う。
実行していない結果を書かない。うまくいかなかったことも記録する価値がある。

## 6. 締める

`/wrap-exp` を使うか、以下を手動で行う。

1. `reports/NNNN-slug.md` を作成する（書き方は `$experiment-report`）
2. `reports/README.md` の索引に行を追加する
3. 日本語 Conventional Commits でコミットし、`git push -u origin exp/NNNN-slug`
4. PR を作成する。本文に **`Closes #<Issue番号>`** を必ず含める

```shell
gh pr create --title "<type>: NNNN <日本語の要約>" --body-file <path>
```

## 7. ここで止まる

**PR をマージしない。** マージは人間が判断する。`gh pr merge` は使わない（permissions で deny されている）。
PR の URL を報告して終える。マージされると Issue は自動でクローズされる。

## 検証を打ち切るとき

うまくいかなかった検証も残す。レポートに「なぜ打ち切ったか」「どこまで分かったか」を書き、
索引の状態を ❌ 断念にして、Issue に `断念` ラベルを付けたうえで PR にする。
