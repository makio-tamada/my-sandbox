# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "psycopg[binary]",
#   "sentence-transformers",
#   "datasets",
#   "anthropic[vertex]",
# ]
# ///
"""合成クエリと実クエリでRAGのRecall@5がどれだけズレるかを実測する(Issue #10)。

    uv run run_query_gap.py | tee run_log.txt

SQuAD(rajpurkar/squad)のcontextをpgvectorに格納し、
(1) クラウドワーカーが書いた実クエリ(question列)と
(2) Claude Haiku 4.5に同じcontextから生成させた合成クエリ
のそれぞれについて、3つの検索構成でRecall@5を比較する。

- baseline      : クエリをそのまま埋め込んで検索
- always_expand : 毎回、言い換え2件を生成してクエリ拡張してから検索
- escalate      : baselineの上位1件の類似度がESCALATE_THRESHOLD未満のときだけ
                   always_expandと同じ処理にエスカレーションする

認証はGCPのADC(`gcloud auth application-default login`)を使う。
ANTHROPIC_API_KEYは使わない(Vertex AI経由)。
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field

import psycopg
from anthropic import AnthropicVertex
from datasets import load_dataset
from sentence_transformers import SentenceTransformer

# --- 設定 ---------------------------------------------------------------
GCP_PROJECT_ID = "solution-projects-509006"
GCP_REGION = "global"
MODEL = "claude-haiku-4-5"  # Vertexでは日付なしの裸IDを使う
DSN = "postgresql://postgres:postgres@localhost:5435/postgres"
N = 30
TOP_K = 5
ESCALATE_THRESHOLD = 0.35  # baseline上位1件のコサイン類似度がこれ未満ならエスカレーション

client = AnthropicVertex(project_id=GCP_PROJECT_ID, region=GCP_REGION)
embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


# --- データ準備 -----------------------------------------------------------
def load_picked_rows() -> list[dict]:
    """SQuAD trainからcontext重複を除いてN件取得する。"""
    squad = load_dataset("rajpurkar/squad", split="train")
    seen: set[str] = set()
    picked: list[dict] = []
    for row in squad:
        if row["context"] not in seen:
            seen.add(row["context"])
            picked.append(row)
        if len(picked) >= N:
            break
    if len(picked) < N:
        print(f"WARNING: context重複除去後 {len(picked)} 件しか集まらなかった(目標 {N} 件)")
    return picked


def setup_db(conn: psycopg.Connection, contexts: list[str]) -> None:
    context_vecs = embedder.encode(contexts)
    conn.execute("DROP TABLE IF EXISTS docs")
    conn.execute("CREATE TABLE docs (id serial PRIMARY KEY, text text, embedding vector(384))")
    with conn.cursor().copy("COPY docs (text, embedding) FROM STDIN") as copy:
        for text, vec in zip(contexts, context_vecs):
            copy.write_row((text, list(map(float, vec))))
    conn.execute("CREATE INDEX ON docs USING hnsw (embedding vector_cosine_ops)")


# --- Claude呼び出し ---------------------------------------------------------
def gen_synthetic_query(passage: str) -> str:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=64,
        messages=[
            {
                "role": "user",
                "content": f"次の文章の内容だけから答えられる質問を1つ、日本語で書いてください。文章:\n{passage}",
            }
        ],
    )
    return msg.content[0].text.strip()


def expand_query(q: str) -> list[str]:
    msg = client.messages.create(
        model=MODEL,
        max_tokens=128,
        messages=[
            {
                "role": "user",
                "content": f"次の検索クエリの言い換えを2つ、改行区切りで出してください。それ以外の文言は含めないでください。クエリ: {q}",
            }
        ],
    )
    lines = [l.strip() for l in msg.content[0].text.splitlines() if l.strip()]
    return lines[:2]


# --- 検索 -----------------------------------------------------------------
def search(conn: psycopg.Connection, vec, k: int = TOP_K) -> list[tuple[int, str, float]]:
    """(id, text, cosine_distance) のリストを返す。距離が小さいほど類似。"""
    rows = conn.execute(
        "SELECT id, text, embedding <=> %s AS distance FROM docs ORDER BY distance LIMIT %s",
        (list(map(float, vec)), k),
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def merge_results(
    result_sets: list[list[tuple[int, str, float]]], k: int = TOP_K
) -> list[tuple[int, str, float]]:
    """複数クエリの検索結果を、doc単位で最小距離を採用してユニーク化しtop-kを再構成する。"""
    best: dict[int, tuple[str, float]] = {}
    for results in result_sets:
        for doc_id, text, distance in results:
            if doc_id not in best or distance < best[doc_id][1]:
                best[doc_id] = (text, distance)
    merged = [(doc_id, text, distance) for doc_id, (text, distance) in best.items()]
    merged.sort(key=lambda x: x[2])
    return merged[:k]


# --- 1クエリぶんの実行結果 ---------------------------------------------------
@dataclass
class QueryRun:
    query_set: str  # "real" | "synthetic"
    config: str  # "baseline" | "always_expand" | "escalate"
    query: str
    hit: bool
    latency_ms: float
    llm_calls: int
    escalated: bool = False
    top1_similarity: float = field(default=0.0)


def run_baseline(conn, query: str, gold_context: str, query_set: str) -> QueryRun:
    t0 = time.perf_counter()
    vec = embedder.encode([query])[0]
    results = search(conn, vec)
    latency_ms = (time.perf_counter() - t0) * 1000
    hit = any(text == gold_context for _, text, _ in results)
    top1_sim = 1 - results[0][2] if results else 0.0
    return QueryRun(query_set, "baseline", query, hit, latency_ms, llm_calls=0, top1_similarity=top1_sim)


def run_always_expand(conn, query: str, gold_context: str, query_set: str) -> QueryRun:
    t0 = time.perf_counter()
    paraphrases = expand_query(query)
    llm_calls = 1  # 言い換え生成は1回のAPI呼び出しで2件まとめて取得
    all_queries = [query] + paraphrases
    result_sets = [search(conn, embedder.encode([q])[0]) for q in all_queries]
    merged = merge_results(result_sets)
    latency_ms = (time.perf_counter() - t0) * 1000
    hit = any(text == gold_context for _, text, _ in merged)
    return QueryRun(query_set, "always_expand", query, hit, latency_ms, llm_calls=llm_calls)


def run_escalate(conn, query: str, gold_context: str, query_set: str) -> QueryRun:
    t0 = time.perf_counter()
    vec = embedder.encode([query])[0]
    base_results = search(conn, vec)
    top1_sim = 1 - base_results[0][2] if base_results else 0.0
    hit = any(text == gold_context for _, text, _ in base_results)
    llm_calls = 0
    escalated = False
    if top1_sim < ESCALATE_THRESHOLD:
        escalated = True
        paraphrases = expand_query(query)
        llm_calls = 1
        all_queries = [query] + paraphrases
        result_sets = [search(conn, embedder.encode([q])[0]) for q in all_queries]
        merged = merge_results(result_sets)
        hit = any(text == gold_context for _, text, _ in merged)
    latency_ms = (time.perf_counter() - t0) * 1000
    return QueryRun(
        query_set, "escalate", query, hit, latency_ms, llm_calls=llm_calls,
        escalated=escalated, top1_similarity=top1_sim,
    )


# --- 集計 -------------------------------------------------------------------
def summarize(runs: list[QueryRun]) -> None:
    print("\n=== Recall@5 (baseline, 実クエリ vs 合成クエリ) ===")
    for qs in ("real", "synthetic"):
        subset = [r for r in runs if r.config == "baseline" and r.query_set == qs]
        recall = 100 * sum(r.hit for r in subset) / len(subset) if subset else 0.0
        print(f"  {qs:10s}: {recall:.1f}% ({sum(r.hit for r in subset)}/{len(subset)})")

    print("\n=== 3構成の平均レイテンシとLLM呼び出し回数/クエリ (実+合成 計60件) ===")
    for config in ("baseline", "always_expand", "escalate"):
        subset = [r for r in runs if r.config == config]
        avg_latency = sum(r.latency_ms for r in subset) / len(subset) if subset else 0.0
        avg_calls = sum(r.llm_calls for r in subset) / len(subset) if subset else 0.0
        recall = 100 * sum(r.hit for r in subset) / len(subset) if subset else 0.0
        print(
            f"  {config:14s}: recall@5={recall:5.1f}%  "
            f"avg_latency={avg_latency:7.1f}ms  avg_llm_calls/query={avg_calls:.2f}"
        )

    escalate_runs = [r for r in runs if r.config == "escalate"]
    escalated = [r for r in escalate_runs if r.escalated]
    rate = 100 * len(escalated) / len(escalate_runs) if escalate_runs else 0.0
    print(f"\n=== エスカレーション発動率 ===\n  {rate:.1f}% ({len(escalated)}/{len(escalate_runs)})")

    if escalated:
        baseline_by_key = {
            (r.query_set, r.query): r for r in runs if r.config == "baseline"
        }
        deltas = []
        for r in escalated:
            b = baseline_by_key.get((r.query_set, r.query))
            if b is not None:
                deltas.append((1 if r.hit else 0) - (1 if b.hit else 0))
        avg_delta_pt = 100 * sum(deltas) / len(deltas) if deltas else 0.0
        print(f"  発動時のRecall@5改善幅: {avg_delta_pt:+.1f}pt (baseline比、n={len(deltas)})")


def write_csv(runs: list[QueryRun], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["query_set", "config", "query", "hit", "latency_ms", "llm_calls", "escalated", "top1_similarity"]
        )
        for r in runs:
            writer.writerow(
                [r.query_set, r.config, r.query, r.hit, f"{r.latency_ms:.1f}", r.llm_calls, r.escalated, f"{r.top1_similarity:.4f}"]
            )
    print(f"\nCSVを書き出した: {path}")


# --- メイン -----------------------------------------------------------------
def main() -> None:
    picked = load_picked_rows()
    contexts = [r["context"] for r in picked]

    with psycopg.connect(DSN, autocommit=True) as conn:
        setup_db(conn, contexts)

        print(f"合成クエリを生成中... ({len(picked)}件)")
        real_queries = [(r["question"], r["context"]) for r in picked]
        synthetic_queries = [(gen_synthetic_query(r["context"]), r["context"]) for r in picked]

        runs: list[QueryRun] = []
        for query_set, queries in (("real", real_queries), ("synthetic", synthetic_queries)):
            for query, gold_context in queries:
                runs.append(run_baseline(conn, query, gold_context, query_set))
                runs.append(run_always_expand(conn, query, gold_context, query_set))
                runs.append(run_escalate(conn, query, gold_context, query_set))

    summarize(runs)
    write_csv(runs, "run_query_gap_results.csv")


if __name__ == "__main__":
    main()
