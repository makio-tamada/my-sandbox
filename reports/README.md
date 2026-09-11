# 検証レポート索引

過去の技術検証の一覧です。**結論列を読むだけで何が分かったかを思い出せる**状態を保ちます。
詳細は各レポートを参照してください。

状態: 🔬 進行中 / ✅ 完了 / ❌ 断念

| 番号 | テーマ | 種別 | 状態 | 結論 | Issue | 日付 |
| --- | --- | --- | --- | --- | --- | --- |
| [0001](0001-pgvector-pool-guc-reset.md) | asyncpgプールのRESET ALLでpgvectorのef_searchが消える問題 | python-project | ✅ 完了 | `init=`のみだと2回目以降のacquireでef_searchが消え、recall@10が97.95%→86.05%(11.9pt)落ちる。`init=`+`setup=`/`server_settings=`/`PGOPTIONS`/`SET LOCAL`は劣化を防げるが、`SET LOCAL`はp50で約1.1msのオーバーヘッドがある | #3 | 2026-09-11 |

## 新しい検証を始める

`/new-exp <テーマ>` を実行すると、Issue の作成・ブランチの作成・雛形の配置まで行われます。
検証が終わったら `/wrap-exp` でレポートを作成し、この索引が更新され、PR が作成されます。
