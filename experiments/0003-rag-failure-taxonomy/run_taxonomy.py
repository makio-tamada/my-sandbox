# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "psycopg[binary]",
#   "sentence-transformers",
#   "transformers",
#   "torch",
#   "datasets",
#   "pandas",
#   "huggingface_hub",
# ]
# ///
"""最小RAG構成(pgvector + MiniLM + SmolLM2)の回答失敗を4分類して実測する。

    uv run run_taxonomy.py

rag-mini-wikipedia の `text-corpus`(3200 passages)と `question-answer`(918問)は
どちらも公開データセットの `id` 列が単なる連番であり、互いに対応していない
(generate.py を確認して判明。詳細は reports/0003-rag-failure-taxonomy.md 参照)。
そのため本スクリプトは、元データ(CMU QA dataset の `ArticleFile` 列とS08生テキスト)から
「質問がどの記事に属するか」「passageがどの記事に属するか」を突き合わせ、
**記事単位**の正解集合を再構築してから recall@5 を計算する
(=「正解の記事に属するpassageが上位5件に入っているか」というやや粗い指標になる)。
"""

from __future__ import annotations

import csv
import glob
import time
from pathlib import Path

import pandas as pd
import psycopg
from datasets import load_dataset
from huggingface_hub import hf_hub_download
from sentence_transformers import SentenceTransformer
from transformers import AutoModelForCausalLM, AutoTokenizer

DSN = "postgresql://postgres:postgres@localhost:5434/postgres"
N_QUESTIONS = 60
TOP_K = 5
DATA_DIR = Path(__file__).parent / ".data"
RAW_TEXT_DIR = DATA_DIR / "raw_text"
S08_FILES = [f"S08_set{s}_a{a}" for s in range(1, 5) for a in range(1, 11)]


def ensure_raw_text_files() -> None:
    RAW_TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for stem in S08_FILES:
        dest = RAW_TEXT_DIR / f"{stem}.txt.clean"
        if dest.exists():
            continue
        src = hf_hub_download(
            "rag-datasets/rag-mini-wikipedia",
            f"raw_data/text_data/{stem}.txt.clean",
            repo_type="dataset",
        )
        dest.write_bytes(Path(src).read_bytes())


def build_article_mapping() -> tuple[pd.DataFrame, dict[int, list[int]]]:
    """質問→ArticleFile、ArticleFile→passage_idリスト、を再構築する。"""
    ensure_raw_text_files()

    # passage本文 -> どのS08ファイル由来か
    text_to_file: dict[str, str] = {}
    for path in glob.glob(str(RAW_TEXT_DIR / "S08*clean")):
        fname = Path(path).name.replace(".txt.clean", "")
        df = pd.read_csv(path, sep="\t", encoding="latin-1", index_col=False)
        df = df.rename(columns={df.columns[0]: "passage"})
        for t in df["passage"].dropna():
            text_to_file[t] = fname

    corpus = load_dataset("rag-datasets/rag-mini-wikipedia", "text-corpus")["passages"]
    file_to_passage_ids: dict[str, list[int]] = {}
    unmatched = 0
    for row in corpus:
        f = text_to_file.get(row["passage"])
        if f is None:
            unmatched += 1
            continue
        file_to_passage_ids.setdefault(f, []).append(row["id"])
    print(f"corpus passages: {len(corpus)}件, source file 特定できず: {unmatched}件")

    # 質問 -> ArticleFile (generate.py と同じ dropna/drop_duplicates の順序を再現し、
    # 公開された question-answer データセットの id 列と行順を一致させる)
    qa_raw_path = hf_hub_download(
        "rag-datasets/rag-mini-wikipedia",
        "raw_data/S08_question_answer_pairs.txt",
        repo_type="dataset",
    )
    qdf = pd.read_csv(qa_raw_path, sep="\t", encoding="latin-1")
    qdf = qdf.rename(columns={"Question": "question", "Answer": "answer"})
    qdf = qdf[["question", "answer", "ArticleFile"]].dropna(
        subset=["question", "answer"]
    )
    qdf = qdf.drop_duplicates(subset="question").reset_index(drop=True)
    qdf["id"] = qdf.index

    return qdf, file_to_passage_ids


def load_into_pgvector(embedder: SentenceTransformer) -> None:
    corpus = load_dataset("rag-datasets/rag-mini-wikipedia", "text-corpus")["passages"]
    texts = list(corpus["passage"])
    ids = list(corpus["id"])
    print(f"corpus embedding計算中... ({len(texts)}件)")
    vecs = embedder.encode(texts, show_progress_bar=True, batch_size=64)

    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS passages")
        conn.execute(
            "CREATE TABLE passages (id integer PRIMARY KEY, text text, embedding vector(384))"
        )
        with conn.cursor() as cur:
            for pid, text, vec in zip(ids, texts, vecs, strict=True):
                vec_str = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
                cur.execute(
                    "INSERT INTO passages (id, text, embedding) VALUES (%s, %s, %s::vector)",
                    (pid, text, vec_str),
                )
        conn.execute(
            "CREATE INDEX ON passages USING hnsw (embedding vector_cosine_ops)"
        )


def main() -> None:
    qdf, file_to_passage_ids = build_article_mapping()

    embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    dim = embedder.get_sentence_embedding_dimension()
    print(f"embedding次元: {dim}")

    load_into_pgvector(embedder)

    tokenizer = AutoTokenizer.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")
    model = AutoModelForCausalLM.from_pretrained("HuggingFaceTB/SmolLM2-135M-Instruct")

    results: list[dict] = []
    with psycopg.connect(DSN) as conn:
        for i in range(min(N_QUESTIONS, len(qdf))):
            row = qdf.iloc[i]
            question, answer, article = (
                row["question"],
                str(row["answer"]),
                row["ArticleFile"],
            )
            gt_ids = set(file_to_passage_ids.get(article, []))

            t0 = time.perf_counter()
            try:
                q_vec = embedder.encode([question])[0]
                vec_str = "[" + ",".join(f"{x:.6f}" for x in q_vec) + "]"
                hits = conn.execute(
                    "SELECT id, text FROM passages ORDER BY embedding <=> %s::vector LIMIT %s",
                    (vec_str, TOP_K),
                ).fetchall()
                t_retrieval = time.perf_counter() - t0
            except Exception as e:  # noqa: BLE001
                results.append(
                    {
                        "q": question,
                        "answer": answer,
                        "article": article,
                        "label": "エラー",
                        "detail": repr(e),
                    }
                )
                continue

            if not hits:
                results.append(
                    {"q": question, "answer": answer, "article": article, "label": "空"}
                )
                continue
            if not gt_ids or gt_ids.isdisjoint(h[0] for h in hits):
                results.append(
                    {
                        "q": question,
                        "answer": answer,
                        "article": article,
                        "label": "圏外",
                        "n_gt_passages": len(gt_ids),
                    }
                )
                continue

            context = "\n".join(h[1] for h in hits[:3])
            prompt = (
                f"Answer the question in a few words, using only the context below.\n"
                f"Context:\n{context}\nQuestion: {question}"
            )
            inputs = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                return_tensors="pt",
                add_generation_prompt=True,
                return_dict=True,
            )
            t1 = time.perf_counter()
            out = model.generate(**inputs, max_new_tokens=32)
            t_gen = time.perf_counter() - t1
            gen_text = tokenizer.decode(
                out[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True
            )

            correct = answer.strip().lower() in gen_text.strip().lower()
            results.append(
                {
                    "q": question,
                    "answer": answer,
                    "article": article,
                    "label": "正解" if correct else "誤答",
                    "gen": gen_text,
                    "t_retrieval": round(t_retrieval, 4),
                    "t_gen": round(t_gen, 4),
                }
            )
            print(
                f"[{i + 1}/{min(N_QUESTIONS, len(qdf))}] {results[-1]['label']}: {question[:40]}"
            )

    # 集計
    labels = [r["label"] for r in results]
    n = len(results)
    counts = {lb: labels.count(lb) for lb in ["空", "圏外", "誤答", "正解", "エラー"]}
    n_no_error = n - counts["エラー"]
    recall_at_5 = (counts["誤答"] + counts["正解"]) / n_no_error if n_no_error else 0.0
    n_retrieval_ok = counts["誤答"] + counts["正解"]
    gen_accuracy = counts["正解"] / n_retrieval_ok if n_retrieval_ok else 0.0
    t_retrievals = [r["t_retrieval"] for r in results if "t_retrieval" in r]
    t_gens = [r["t_gen"] for r in results if "t_gen" in r]

    print("\n=== 集計 ===")
    print(f"件数: {n}")
    print(f"内訳: {counts}")
    print(f"recall@5 (= (誤答+正解)/(空・圏外を除く全体)): {recall_at_5:.4f}")
    print(f"retrieval成功時の生成正答率 (= 正解/(正解+誤答)): {gen_accuracy:.4f}")
    if t_retrievals:
        print(f"平均 t_retrieval: {sum(t_retrievals) / len(t_retrievals):.4f}秒")
    if t_gens:
        print(f"平均 t_gen: {sum(t_gens) / len(t_gens):.4f}秒")

    DATA_DIR.mkdir(exist_ok=True)
    csv_path = DATA_DIR / "results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "q",
            "answer",
            "article",
            "label",
            "gen",
            "t_retrieval",
            "t_gen",
            "n_gt_passages",
            "detail",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\n結果を {csv_path} に保存した")


if __name__ == "__main__":
    main()
