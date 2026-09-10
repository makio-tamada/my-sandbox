---
description: 検証結果をレポートにまとめ、索引を更新して PR を作成する
---

検証を締めて Pull Request まで作成してください。

対象: $ARGUMENTS （省略時は現在のブランチ名から `NNNN` と slug を判定する）

`$experiment-report` の作法に従い、以下を順に実行します。

1. **実行結果を確認する。** レポートに書く数値は、このセッションで実際に実行して得たものだけを使う。
   手元に実測値がない項目は、書く前に実行するか「未検証」と明記する

2. **レポートを作成する。** `templates/REPORT.md` を元に `reports/NNNN-slug.md` を書く

   - 冒頭の**結論を 1 行**で先出しする
   - 「前提・計測環境」にマシン・Python とライブラリのバージョン・データ規模を記録する
   - 「手順」には実際に叩いたコマンドをそのまま載せる
   - 実測値は「結果」、解釈は「考察」に分けて書く
   - 図表があれば `reports/assets/NNNN-slug/` に置く

3. **索引を更新する。** `reports/README.md` の表に行を追加する。
   状態は ✅ 完了 / ❌ 断念、結論列は一覧で読める 1 行にする

4. **コミットして push する。** 日本語 Conventional Commits を使う

   ```shell
   git add -A
   git commit -m "feat: NNNN <日本語の要約>"
   git push -u origin exp/NNNN-slug
   ```

5. **PR を作成する。** 本文に **`Closes #<Issue番号>`** を必ず含める。
   Issue 番号が不明なら `gh issue list` で確認する

   ```shell
   gh pr create --title "feat: NNNN <日本語の要約>" --body-file <path>
   ```

6. **PR の URL を報告して停止する**

**マージしないでください。** マージは人間が判断します（`gh pr merge` は permissions で deny されています）。
PR がマージされると Issue は `Closes #N` によって自動でクローズされます。
