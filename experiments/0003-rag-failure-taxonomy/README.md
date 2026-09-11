# 0003: 最小RAG構成の回答失敗を4分類で実測する

<!-- ここには動かし方だけを書く。結果と考察は reports/0003-rag-failure-taxonomy.md に書く -->

## 動かし方

```shell
docker compose up -d
docker compose exec db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS vector;"

uv run run_taxonomy.py
```

初回実行時に GloVeではなく rag-mini-wikipedia のパッセージ(3200件)・SmolLM2-135M-Instruct・
MiniLM をダウンロードする（合計約1GB弱）。結果は `.data/results.csv` に保存される。

## 注意

- `rag-mini-wikipedia` の `text-corpus` と `question-answer` の `id` 列は互いに対応していない
  （データセット付属の `generate.py` を確認して判明。詳細は `run_taxonomy.py` の docstring と
  `reports/0003-rag-failure-taxonomy.md` を参照）。そのため本スクリプトは元データの
  `ArticleFile` 列とS08生テキストファイルから記事単位の正解集合を再構築している
- `.data/` はダウンロードしたモデル・中間データを置く場所で、`.gitignore` 済み
- 元Issueの計画（100問）から規模を縮小し、60問で実施した

## 品質チェック

```shell
uvx ruff check .
uvx ruff format --check .
```

`python-script` 種別のため pyproject.toml は持たない。`/verify experiments/0003-rag-failure-taxonomy`
は `uv run run_taxonomy.py` が完走することの確認に読み替えられる。
