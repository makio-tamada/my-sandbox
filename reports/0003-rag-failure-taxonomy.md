# 0003: 最小RAG構成の回答失敗を4分類で実測する

**結論**: recall@5（記事単位）は90.0%と高かったが、正解の記事が検索できたケースに限っても生成の正答率は42.6%しかなく、「検索は当たっているのに誤答する」ケース（誤答31件）が「空」（0件）「圏外」（6件）を合わせた数を大きく上回った。レイテンシは生成（平均0.61秒）が検索（平均0.04秒）の約15倍で支配的。

| 項目 | 値 |
| --- | --- |
| Issue | #5 |
| PR | (このレポートと同じPRで作成) |
| 実施日 | 2026-09-11 |
| 種別 | python-script |
| 状態 | ✅ 完了 |
| コード | [experiments/0003-rag-failure-taxonomy/](../experiments/0003-rag-failure-taxonomy/) |

## 何を確かめたかったか

公開QAデータセットに対する最小RAG構成（pgvector + 公開埋め込みモデル + 公開小型LLM）を組み、質問への回答失敗を「検索結果が空」「上位に正解文書が入らない（圏外）」「正解文書は取得できたのに回答が誤る」「エラー」の4分類に振り分けたとき、それぞれ何件・何%起きるかを実測することが目的。

## 前提・計測環境

| 項目 | 内容 |
| --- | --- |
| マシン | Apple M4 Max (arm64) |
| Python | 3.12.8（`uv run`、CPU推論） |
| 主要ライブラリ | transformers 5.17.0 / torch 2.14.0 / sentence-transformers 6.0.1 / datasets 5.0.1 / psycopg 3.3.5 |
| DB | `pgvector/pgvector:pg17`（PostgreSQL 17.11、Docker） |
| 埋め込みモデル | sentence-transformers/all-MiniLM-L6-v2（384次元） |
| 生成モデル | HuggingFaceTB/SmolLM2-135M-Instruct（CPU） |
| データセット | rag-mini-wikipedia（text-corpus 3200件、question-answer 918件） |
| 質問数 | 60問（元Issueの計画は100問。縮小） |
| 試行回数 | 1回のみ（**未検証**: 複数回実行したときのばらつき） |

## 手順（再現方法）

```shell
cd experiments/0003-rag-failure-taxonomy
docker compose up -d
docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"
uv run run_taxonomy.py
```

## 重要な前提のずれと、その対処（実行前に判明）

Issueは「質問ごとに正解passage IDと正解文が付いている」ことを前提に recall@k を直接計算する想定だったが、実際に `rag-mini-wikipedia` の2つのconfig（`text-corpus` と `question-answer`）を読み込んで確認したところ、**両者の `id` 列は互いに対応していなかった**（例: question id=0 「Was Abraham Lincoln...」に対し、corpus id=0 は "Uruguay" に関する文章で無関係）。

原因をデータセット付属の `generate.py` で確認したところ、`text-corpus` と `question-answer` はそれぞれ独立に `pandas` の `dropna()` → `drop_duplicates()` → 連番インデックス振り直し、という処理で作られており、**2つのconfigの `id` は単なる連番であって、互いのリンクを意図していない**ことが分かった。

これに対応するため、元になった CMU Question-Answer Dataset の生データ（`raw_data/S08_question_answer_pairs.txt` の `ArticleFile` 列、および `raw_data/text_data/S08_set*_a*.txt.clean` の40ファイル）を取得し、以下の手順で**記事単位の正解集合**を独自に再構築した:

1. 40個の生テキストファイルそれぞれを読み、収録されているpassage本文をキーに「どのファイル（記事）由来か」の辞書を作る
2. `text-corpus` の3200件全passageをこの辞書と突き合わせ、100%（3200/3200件）が元ファイルに一致することを確認した
3. `S08_question_answer_pairs.txt` を `generate.py` と同じ dropna/drop_duplicates の順序で読み直し、公開された `question-answer` の918件と行順・内容が一致すること（918/918件、うち文字コード起因の6件を除き完全一致）を確認した
4. 各質問の `ArticleFile` と、同じ記事に属するpassage群（1記事あたり平均80件、最小9件・最大174件、記事数40）を突き合わせ、「正解の記事に属するどれか1件でも上位k件に入っているか」を recall@k として計算した

**この結果、本検証の recall@5 は「正解の一節そのもの」ではなく「正解の記事に属するpassageのどれか」を検索できたかを見る、やや粗い指標になっている。** 1記事あたり平均80件（全3200件の約2.5%）が「正解」扱いになるため、厳密な一文単位のrecallより数値は高めに出やすい点に注意が必要。

## 結果

### 4分類の内訳（60問）

| ラベル | 件数 | 割合 |
| --- | --- | --- |
| 空（検索結果0件） | 0 | 0.0% |
| 圏外（正解記事のpassageが上位5件に入らない） | 6 | 10.0% |
| 誤答（正解記事は検索できたが生成が誤り） | 31 | 51.7% |
| 正解 | 23 | 38.3% |

### 主要な3指標

| 指標 | 値 |
| --- | --- |
| recall@5（記事単位。= (誤答+正解件数) / 全60問） | **90.0%** |
| retrieval成功時の生成正答率（= 正解 / (正解+誤答)） | **42.6%** |
| 平均 t_retrieval | 0.0412秒 |
| 平均 t_gen | 0.6098秒 |

recall@5は仮説「8割前後」よりやや高い90.0%だった。一方、retrieval成功時の生成正答率は42.6%と半分を下回り、「検索は当たっているのに生成が誤答する」件数（31件）は「空」+「圏外」の合計（6件）を大きく上回った。仮説「誤答が空・圏外より多い」は的中した。

レイテンシは生成（0.61秒）が検索（0.04秒）の約15倍で、仮説通り生成側が支配的だった（ただしSmolLM2-135Mは意図的に小さいモデルであり、絶対値は仮説の「数秒〜十数秒」より大幅に速かった）。

### 誤答の具体例（5件。完了条件の「3件以上」を満たす）

| 質問 | 正解 | 生成結果 |
| --- | --- | --- |
| Who suggested Lincoln grow a beard? | 11-year-old Grace Bedell | Abraham Lincoln's official White House portrait |
| Was Abraham Lincoln the first President of the United States? | No | Yes, Abraham Lincoln was the first President of the United States. |
| Did Lincoln ever represent Alton & Sangamon Railroad? | Yes | Lincoln never represented the Alton & Sangamon Railroad. |
| Which county was Lincoln born in? | Hardin County | Lincoln was born in Springfield, Illinois. |
| Who assassinated Lincoln? | John Wilkes Booth | The assassination of Abraham Lincoln. |

観察できたパターン:
- **Yes/No反転**: 正解が「No」なのに「Yes」と断定して答える（2・3件目）。文脈に答えが書いてあっても小型モデルが逆に読み取っている
- **無関係な文の生成**: 質問文をなぞるだけで具体的な答えを出さない（1・5件目、「Who」に対して人物名を出さず関連語句を並べるだけ）
- **文脈と矛盾する具体値の生成**: 「Hardin County」が正解のところ「Springfield, Illinois」という、文脈中に実在する別の地名を答えてしまう（4件目。ハルシネーションというより、文脈内の別の事実との混同）

## 考察

- **recall@kだけを見ていると、この構成の実際の失敗率（60問中37件≒6割強が最終的に誤り）を見落とす。** recall@5は90%と高く「検索は概ねうまくいっている」ように見えるが、エンドツーエンドの正答率は 23/60 = 38.3% に過ぎない
- **失敗の大半は生成側にある。** 4分類の内訳では「誤答」が最多（51.7%）で、「空」「圏外」を合わせた10.0%を大きく上回った。検索品質の改善（recall向上）よりも、生成モデルの指示追従性やYes/No判定の精度改善の方が、このRAG構成の実効性向上には効きそうだと推測される
- **これはSmolLM2-135M-Instructという意図的に小さいモデルを使った結果であり、より大きなモデルでは生成正答率は改善すると見込まれる。** 本検証は「検索と生成を切り分けて観測できる」ことを主眼に置いており、絶対値としての42.6%を一般のRAG構成の代表値として扱うべきではない
- **recall@5の指標自体が記事単位の粗い代用指標である点は、結果の解釈に影響する。** 1記事平均80件が「正解」とみなされるため、厳密な一文単位の検索精度はこれより低い可能性がある

## 未検証・残課題

- Issue通りの規模（100問）で実行した場合の数値（今回は60問に縮小）
- より大きな生成モデル（例: Claude Haiku等）に差し替えた場合の生成正答率の変化
- 複数回試行によるばらつき（今回は1回のみ）
- 記事単位ではなく、一節（文）単位の厳密な正解データでの recall@5（今回のデータセットには付属していないため、独自にアノテーションするか、正解passage粒度の別データセットに切り替える必要がある）
- 「圏外」6件・「エラー」0件について、質問の性質（曖昧さ、語彙の乖離など）との相関分析

## 参考リンク

- https://developer.ibm.com/technologies/rag/
- https://huggingface.co/datasets/rag-datasets/rag-mini-wikipedia
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct
