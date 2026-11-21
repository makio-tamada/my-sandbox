# 検証レポート索引

過去の技術検証の一覧です。**結論列を読むだけで何が分かったかを思い出せる**状態を保ちます。
詳細は各レポートを参照してください。

状態: 🔬 進行中 / ✅ 完了 / ❌ 断念

| 番号 | テーマ | 種別 | 状態 | 結論 | Issue | 日付 |
| --- | --- | --- | --- | --- | --- | --- |
| [0001](0001-pgvector-pool-guc-reset.md) | asyncpgプールのRESET ALLでpgvectorのef_searchが消える問題 | python-project | ✅ 完了 | `init=`のみだと2回目以降のacquireでef_searchが消え、recall@10が97.95%→86.05%(11.9pt)落ちる。`init=`+`setup=`/`server_settings=`/`PGOPTIONS`/`SET LOCAL`は劣化を防げるが、`SET LOCAL`はp50で約1.1msのオーバーヘッドがある | #3 | 2026-09-11 |
| [0003](0003-rag-failure-taxonomy.md) | 最小RAG構成の回答失敗を4分類で実測する | python-script | ✅ 完了 | recall@5(記事単位)は90.0%と高いが、正解記事を検索できたケースでも生成正答率は42.6%しかなく、誤答(31件)が空+圏外(6件)を大きく上回る | #5 | 2026-09-11 |
| [0004](0004-jquants-smallcap-backtest.md) | 小型株スクリーニング + 値幅ルールのバックテスト | python-project | ✅ 完了 | in-sample で PF 4.35 だった条件が out-of-sample では PF 0.93 に反転。条件を 243 通り振っても in→out の順位相関は -0.05 でほぼ無相関 | #8 | 2026-09-18 |
| [0006](0006-pydantic-json-memory-regression.md) | pydantic 2.14.4 で model_validate_json のメモリ回帰が解消したか実測する | python-script | ✅ 完了 | 47MBのJSONでピークRSSが2.14.1→2.14.2/2.14.3で+86MB(+15〜19%)、2.14.4では2.14.1より−70MB。Python側の確保量は4版同じで、差はmalloc_trimで返せる領域。from_jsonはメモリ不変だが2.14.2以降約16%遅いまま | #15 | 2026-11-21 |

## 新しい検証を始める

`/new-exp <テーマ>` を実行すると、Issue の作成・ブランチの作成・雛形の配置まで行われます。
検証が終わったら `/wrap-exp` でレポートを作成し、この索引が更新され、PR が作成されます。
