---
name: create-pr
description: Pull Request を作成する。PR を出す、変更を提出する、レビューに回す、PR の本文やタイトルを直す、といったときに使用する。検証を締める場合は /wrap-exp から呼ばれる。
---

# Pull Request の作成

**このリポジトリでは Claude が PR を作成し、マージは人間が判断する。**
`gh pr merge` は使わない（permissions で deny されている）。

## 1. 前提を確認する

```shell
git branch --show-current   # main なら中断する
git status --short          # コミットしていない変更がないか
gh issue list --state open  # 紐づける Issue の番号
```

- **`main` にいたら PR を作らない。** ブランチを切り、変更を移してから出直す
- **紐づける Issue がなければ先に作る。** Issue のない PR を出さない
- **`exp/` `fix/` ブランチ（検証系）は `reports/NNNN-slug.md` が実在し、`git status` に含まれているかを
  `ls reports/NNNN-slug.md` で確認する。** レポートがなければ PR を作らず、先に `$experiment-report` の
  作法で作成する。「レポートへのリンクを本文に書いた」だけでは不十分で、ファイル自体がコミットされている
  ことを確認する
- ブランチ名が `CLAUDE.md` の命名規則に沿っているか確認する
  （検証は `exp/<NNNN>-<slug>`、それ以外は `<type>/<Issue番号>-<slug>`）

## 2. コミットする

日本語 Conventional Commits を使う。`<type>: <日本語の要約>`。

```shell
git add -A
git commit -m "feat: 0003 Polars と DuckDB の集計速度を比較"
git push -u origin <ブランチ名>
```

push する前に、`.env` や `.venv/`、キャッシュ、巨大なデータが混ざっていないか確認する。

```shell
git ls-files | grep -E '\.env$|\.venv|__pycache__|\.pyc'
```

## 3. 本文を書く

`.github/PULL_REQUEST_TEMPLATE.md` の構成に沿ってファイルに書き出す。
`gh pr create --body-file <path>` を使う（本文が長いので `--body` に直接書かない）。

| 欄 | 書くこと |
| --- | --- |
| `Closes #N` | **必須。1 行目に置く。** これがないとマージしても Issue が閉じない |
| 検証したこと | 何を確かめたのか 1〜3 行 |
| 結果サマリ | 結論を先出し。数値は実際に実行して得たものだけ |
| レポート | `reports/NNNN-slug.md` への **Markdown リンク**（例: `[reports/NNNN-slug.md](../reports/NNNN-slug.md)`）。検証以外の PR では省略可 |
| 未検証・残課題 | **確かめていないことを正直に書く。** なければ「なし」 |

**動作確認の欄は、実際に実行したことだけを書く。** 実行していないものを「確認した」と書かない。
実行できなかったもの（課金が発生する、環境がない、試すと副作用がある）は、
理由を添えて「未検証」に回す。

**検証系 PR を作成する直前のチェック項目:**

- [ ] `reports/NNNN-slug.md` がファイルとして存在し、`git ls-files` に含まれている
- [ ] `reports/README.md` の索引にその検証の行が追加されている
- [ ] PR 本文の「レポート」欄が壊れていない Markdown リンクになっている（空の `<a>` タグなどにしない）

## 4. 作成する

タイトルはコミットと同じ日本語 Conventional Commits の形にする。

```shell
gh pr create --title "<type>: <日本語の要約>" --body-file <path>
```

## 5. 紐付けを確認する

`Closes #N` が本文にあるだけでは不十分で、GitHub 側でリンクが成立しているかを確認する。

```shell
gh api graphql -f query='{repository(owner:"makio-tamada",name:"my-sandbox"){
  pullRequest(number:<PR番号>){closingIssuesReferences(first:5){nodes{number title state}}}}}' \
  --jq '.data.repository.pullRequest.closingIssuesReferences.nodes'
```

対象の Issue が返ってこなければ `Closes #N` の書き方が間違っている。本文を直す（次項）。

## 6. 報告して止まる

PR の URL と、未検証として残した項目を報告する。**マージしない。**

## 既存の PR を直すとき

**`gh pr edit` はこのリポジトリでは失敗する。** Projects classic の廃止エラーが返る
（`gh issue edit` も同様）。REST API を使う。

```shell
# 本文を差し替える
gh api -X PATCH repos/makio-tamada/my-sandbox/pulls/<PR番号> -F body=@<path>

# タイトルを差し替える
gh api -X PATCH repos/makio-tamada/my-sandbox/pulls/<PR番号> -f title="<新しいタイトル>"
```

`-F body=@<path>` はファイルから読み込む形式、`-f` は文字列をそのまま渡す形式で、使い分けに注意する。

コードを直した場合は、PR を作り直さず同じブランチに追加コミットして push すれば PR に反映される。
