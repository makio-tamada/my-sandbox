---
description: 検証の Issue を作成し、ブランチを切って雛形を用意する
---

引数のテーマで新しい技術検証を開始してください。

テーマ: $ARGUMENTS

`$experiment-workflow` の手順に従い、以下を順に実行します。

1. **番号と slug を決める**

   ```shell
   ls experiments/
   ```

   既存の最大番号 + 1 を 4 桁ゼロ埋めで `NNNN` とする。テーマから英小文字 kebab-case の slug を作る
   （日本語・アンダースコア・大文字は使わない。2〜5 語、名詞句）。

2. **Issue を作成する。** 本文には「確かめたいこと」「仮説・予想」「完了条件」を書く。
   テーマに応じて `python` / `llm` / `data` / `infra` からラベルを選び、`experiment` と併せて付ける

   ```shell
   gh issue create --title "[検証] <テーマ>" --body-file <path> --label experiment,<種別ラベル>
   ```

3. **ブランチを切る**

   ```shell
   git switch -c exp/NNNN-slug
   ```

4. **雛形をコピーする。** 種別（`python-script` / `python-project` / `llm-anthropic`）を選び、
   `templates/<種別>/` を `experiments/NNNN-slug/` にコピーする。
   判断に迷う場合はユーザーに確認する

5. **`experiments/NNNN-slug/README.md` を書く。** **動かし方だけ**を書く。結果や考察は書かない
   （それは `reports/NNNN-slug.md` の役割）

6. **報告する。** Issue 番号と URL、ブランチ名、作成したディレクトリ、次に実行するコマンドを伝える

注意点:

- 番号・slug は**ブランチ名・ディレクトリ名・後で作るレポート名の 3 つで完全一致**させる
- レポートはこの時点では作らない。検証が終わってから `/wrap-exp` で作る
