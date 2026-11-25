# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "anthropic>=1.4",
#   "python-dotenv>=1.0",
#   "numpy>=2.0",
#   "sentence-transformers>=3.0",
#   "datasets>=3.0",
# ]
# ///
"""合成クエリで評価した RAG 検索構成の優劣は、人間のクエリでも保たれるか（Issue #19）。

    uv run run_query_gap.py --pairs 5      # 試走
    uv run run_query_gap.py --pairs 30     # 全工程
    uv run run_query_gap.py --pairs 200    # 拡大
    python3 run_query_gap.py --fake --pairs 30   # API・ダウンロードなしの動作確認（数値は意味を持たない）

SQuAD v1.1 の validation split を記事単位で「開発用」と「評価用」に分ける。各パッセージから
(1) 文書を見て書かれた人間のクエリ（SQuAD の question）と (2) LLM が生成した合成クエリを
1 件ずつ作ってペアにし、3 つの検索構成で評価する。

- baseline      : クエリをそのまま埋め込んで厳密検索（全件のコサイン類似度）
- always_expand : 毎回、言い換え 2 件を生成し、元クエリと合わせた 3 本の結果を RRF で統合
- escalate      : baseline の上位 1 件の類似度が閾値未満のときだけ always_expand と同じ処理

閾値は開発用の合成クエリで決めて固定する（評価用データでは調整しない）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import config as cfg

HERE = Path(__file__).parent
RUNS_DIR = HERE / "runs"
CACHE_DIR = RUNS_DIR / "cache"
QUERY_TYPES = ("human", "synthetic")
CONFIGS = ("baseline", "always_expand", "escalate")

STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "from",
    "by",
    "with",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "when",
    "where",
    "why",
    "how",
    "did",
    "do",
    "does",
    "that",
    "this",
    "these",
    "those",
    "it",
    "its",
    "as",
    "into",
    "than",
    "then",
    "there",
    "their",
    "they",
    "he",
    "she",
    "his",
    "her",
    "you",
    "your",
    "i",
    "we",
    "our",
    "not",
    "no",
    "can",
    "could",
    "would",
    "should",
    "will",
    "may",
    "might",
    "has",
    "have",
    "had",
}


# ---------------------------------------------------------------------------
# データ
# ---------------------------------------------------------------------------
@dataclass
class Passage:
    pid: int
    title: str
    text: str
    questions: list[str]


def load_squad(fake: bool) -> list[Passage]:
    """SQuAD validation を読み、パッセージ単位にまとめる。"""
    if fake:
        return make_fake_squad()
    from datasets import load_dataset

    ds = load_dataset("rajpurkar/squad", split=cfg.SQUAD_SPLIT)
    by_text: dict[str, Passage] = {}
    for row in ds:
        p = by_text.get(row["context"])
        if p is None:
            p = Passage(len(by_text), row["title"], row["context"], [])
            by_text[row["context"]] = p
        p.questions.append(row["question"])
    return list(by_text.values())


def make_fake_squad() -> list[Passage]:
    """--fake 用の小さな擬似データ。ロジックの確認用で、結果に意味はない。"""
    rng = random.Random(0)
    vocab = [f"w{i}" for i in range(400)]
    passages = []
    for t in range(12):
        topic = rng.sample(vocab, 30)
        for _ in range(15):
            words = [
                rng.choice(topic) if rng.random() < 0.6 else rng.choice(vocab)
                for _ in range(60)
            ]
            text = " ".join(words) + "."
            qs = [
                " ".join(rng.sample(words, 6) + rng.sample(vocab, 3)) + "?"
                for _ in range(3)
            ]
            passages.append(Passage(len(passages), f"Article{t}", text, qs))
    return passages


def split_articles(passages: list[Passage]) -> tuple[set[str], set[str]]:
    titles = sorted({p.title for p in passages})
    rng = random.Random(cfg.SEED)
    rng.shuffle(titles)
    n_dev = (
        min(cfg.DEV_ARTICLE_COUNT, len(titles) // 3)
        if len(titles) < 48
        else cfg.DEV_ARTICLE_COUNT
    )
    return set(titles[:n_dev]), set(titles[n_dev:])


@dataclass
class Pair:
    split: str  # dev / eval
    pid: int
    title: str
    human_query: str


def sample_pairs(
    passages: list[Passage], titles: set[str], n: int, split: str
) -> list[Pair]:
    """記事をまたいでパッセージを無作為抽出し、人間クエリを 1 件ずつ選ぶ。"""
    rng = random.Random(f"{cfg.SEED}-{split}")
    pool = sorted((p for p in passages if p.title in titles), key=lambda p: p.pid)
    chosen = rng.sample(pool, min(n, len(pool)))
    return [Pair(split, p.pid, p.title, rng.choice(p.questions)) for p in chosen]


# ---------------------------------------------------------------------------
# 埋め込みと検索（厳密検索）
# ---------------------------------------------------------------------------
class Embedder:
    def __init__(self, fake: bool):
        self.fake = fake
        if not fake:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(cfg.EMBED_MODEL)

    def encode(self, texts: list[str]) -> np.ndarray:
        if self.fake:
            vecs = np.zeros((len(texts), 256), dtype=np.float32)
            for i, t in enumerate(texts):
                for tok in tokenize(t):
                    vecs[i, int(hashlib.md5(tok.encode()).hexdigest(), 16) % 256] += 1.0
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            return vecs / np.maximum(norms, 1e-9)
        return self.model.encode(
            texts, normalize_embeddings=True, convert_to_numpy=True, batch_size=64
        )


class Index:
    def __init__(self, embedder: Embedder, passages: list[Passage]):
        self.embedder = embedder
        self.pids = np.array([p.pid for p in passages])
        self.matrix = embedder.encode([p.text for p in passages])

    def search(self, query: str, k: int) -> tuple[list[int], list[float], float]:
        """(pid のリスト, 類似度のリスト, 検索にかかった ms) を返す。"""
        t0 = time.perf_counter()
        q = self.embedder.encode([query])[0]
        sims = self.matrix @ q
        top = np.argpartition(-sims, k)[:k]
        top = top[np.argsort(-sims[top])]
        ms = (time.perf_counter() - t0) * 1000
        return [int(self.pids[i]) for i in top], [float(sims[i]) for i in top], ms


def rrf(rankings: list[list[int]], k: int) -> list[int]:
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, pid in enumerate(ranking, start=1):
            scores[pid] += 1.0 / (cfg.RRF_K + rank)
    return [pid for pid, _ in sorted(scores.items(), key=lambda x: -x[1])][:k]


# ---------------------------------------------------------------------------
# LLM（結果はキャッシュして再実行時に再利用する。生成物はコミットして公開する）
# ---------------------------------------------------------------------------
class LLM:
    def __init__(self, fake: bool):
        self.fake = fake
        self.client = None
        if not fake:
            from client import build_client

            self.client = build_client()
        self.cache_path = CACHE_DIR / (
            "llm_cache_fake.jsonl" if fake else "llm_cache.jsonl"
        )
        self.cache: dict[str, dict] = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                self.cache[rec["key"]] = rec

    def _call(self, kind: str, prompt: str, max_tokens: int) -> dict:
        key = hashlib.sha256(
            f"{cfg.MODEL_ID}|{cfg.TEMPERATURE}|{max_tokens}|{prompt}".encode()
        ).hexdigest()
        if key in self.cache:
            return self.cache[key]
        t0 = time.perf_counter()
        if self.fake:
            words = tokenize(prompt.split(":")[-1])
            rng = random.Random(key)
            text = " ".join(rng.sample(words, min(8, len(words)))) + "?"
            if kind == "expand":
                text = "\n".join(
                    " ".join(rng.sample(words, max(1, len(words) - 2)))
                    for _ in range(2)
                )
            usage = {"input_tokens": len(prompt) // 4, "output_tokens": len(text) // 4}
            stop_reason = "end_turn"
        else:
            resp = self.client.messages.create(
                model=cfg.MODEL_ID,
                max_tokens=max_tokens,
                temperature=cfg.TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            ).strip()
            usage = {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
            stop_reason = resp.stop_reason
        rec = {
            "key": key,
            "kind": kind,
            "model": cfg.MODEL_ID,
            "temperature": cfg.TEMPERATURE,
            "max_tokens": max_tokens,
            "prompt": prompt,
            "text": text,
            "usage": usage,
            "stop_reason": stop_reason,
            "llm_ms": (time.perf_counter() - t0) * 1000,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.cache[key] = rec
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def synthetic_query(self, passage: str) -> dict:
        rec = self._call(
            "synthetic",
            cfg.SYNTHETIC_PROMPT.format(passage=passage),
            cfg.MAX_TOKENS_SYNTHETIC,
        )
        return {
            **rec,
            "query": rec["text"].splitlines()[0].strip() if rec["text"] else "",
        }

    def expand(self, query: str) -> dict:
        rec = self._call(
            "expand", cfg.EXPAND_PROMPT.format(query=query), cfg.MAX_TOKENS_EXPAND
        )
        lines = [
            re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", l).strip()
            for l in rec["text"].splitlines()
        ]
        rewrites = [l for l in lines if l][:2]
        return {**rec, "rewrites": rewrites, "malformed": len(rewrites) != 2}


# ---------------------------------------------------------------------------
# クエリの特徴量（原因の断定ではなく、記録のため）
# ---------------------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def query_features(query: str, passage: str) -> dict:
    q_tokens = [t for t in tokenize(query) if t not in STOPWORDS]
    p_tokens = set(tokenize(passage))
    overlap = sum(t in p_tokens for t in q_tokens) / len(q_tokens) if q_tokens else 0.0
    # 固有表現の簡易代替: 文頭以外の大文字始まり語と数字の数（NER モデルは使わない）
    words = re.findall(r"\b\w+\b", query)
    proper = sum(
        1 for i, w in enumerate(words) if i > 0 and (w[0].isupper() or w.isdigit())
    )
    return {
        "content_overlap": round(overlap, 4),
        "query_len_words": len(words),
        "proper_or_number_count": proper,
    }


# ---------------------------------------------------------------------------
# 1 クエリの評価
# ---------------------------------------------------------------------------
def rank_metrics(ranked: list[int], gold: int) -> tuple[int, float]:
    top = ranked[: cfg.TOP_K]
    if gold in top:
        r = top.index(gold) + 1
        return 1, 1.0 / r
    return 0, 0.0


def evaluate_query(index: Index, llm: LLM, query: str, gold: int) -> dict:
    """3 構成ぶんの結果をまとめて返す。拡張結果は常時拡張とエスカレーションで共有する。"""
    base_pids, base_sims, base_ms = index.search(query, cfg.CANDIDATES_PER_QUERY)
    hit, rr = rank_metrics(base_pids, gold)
    exp = llm.expand(query)
    rankings = [base_pids]
    exp_search_ms = 0.0
    for rw in exp["rewrites"]:
        pids, _, ms = index.search(rw, cfg.CANDIDATES_PER_QUERY)
        rankings.append(pids)
        exp_search_ms += ms
    fused = rrf(rankings, cfg.CANDIDATES_PER_QUERY)
    exp_hit, exp_rr = rank_metrics(fused, gold)
    return {
        "top1_sim": base_sims[0],
        "baseline": {"hit": hit, "rr": rr, "search_ms": base_ms},
        "expanded": {
            "hit": exp_hit,
            "rr": exp_rr,
            "search_ms": base_ms + exp_search_ms,
            "llm_ms": exp["llm_ms"],
            "input_tokens": exp["usage"]["input_tokens"],
            "output_tokens": exp["usage"]["output_tokens"],
            "rewrites": exp["rewrites"],
            "malformed": exp["malformed"],
        },
    }


def config_result(r: dict, config: str, threshold: float) -> dict:
    """1 クエリの結果を、指定構成での hit / rr / コストに変換する。"""
    b, e = r["baseline"], r["expanded"]
    use_exp = config == "always_expand" or (
        config == "escalate" and r["top1_sim"] < threshold
    )
    if not use_exp:
        return {
            "hit": b["hit"],
            "rr": b["rr"],
            "llm_calls": 0,
            "search_ms": b["search_ms"],
            "llm_ms": 0.0,
            "tokens": 0,
            "escalated": False,
        }
    return {
        "hit": e["hit"],
        "rr": e["rr"],
        "llm_calls": 1,
        "search_ms": e["search_ms"],
        "llm_ms": e["llm_ms"],
        "tokens": e["input_tokens"] + e["output_tokens"],
        "escalated": config == "escalate",
    }


# ---------------------------------------------------------------------------
# 閾値の決定（開発用データ）
# ---------------------------------------------------------------------------
def choose_threshold(rows: list[dict]) -> float:
    """baseline の失敗を「上位 1 件の類似度 < 閾値」で見分ける力が最大になる閾値（Youden の J）。

    拡張の効果は見ずに決めるので、評価用データの結果を先取りしない。
    """
    sims = sorted({round(r["top1_sim"], 4) for r in rows})
    candidates = [s + 1e-6 for s in sims]
    miss = [r for r in rows if not r["baseline"]["hit"]]
    hit = [r for r in rows if r["baseline"]["hit"]]
    if not miss or not hit:
        return float(statistics.median(sims))
    best, best_j = candidates[0], -1.0
    for t in candidates:
        tpr = sum(r["top1_sim"] < t for r in miss) / len(miss)
        fpr = sum(r["top1_sim"] < t for r in hit) / len(hit)
        if tpr - fpr > best_j:
            best, best_j = t, tpr - fpr
    return round(best, 4)


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------
def aggregate(rows: list[dict], threshold: float) -> dict:
    """rows: 1 行 = 1 クエリ（split, title, pid, qtype, ...）。"""
    out = {}
    for qtype in QUERY_TYPES:
        sub = [r for r in rows if r["qtype"] == qtype]
        for config in CONFIGS:
            res = [config_result(r, config, threshold) for r in sub]
            total_ms = [x["search_ms"] + x["llm_ms"] for x in res]
            out[f"{qtype}/{config}"] = {
                "n": len(res),
                "recall_at_5": mean([x["hit"] for x in res]),
                "mrr_at_5": mean([x["rr"] for x in res]),
                "llm_calls_per_query": mean([x["llm_calls"] for x in res]),
                "tokens_per_query": mean([x["tokens"] for x in res]),
                "latency_median_ms": pct(total_ms, 50),
                "latency_p95_ms": pct(total_ms, 95),
                "search_median_ms": pct([x["search_ms"] for x in res], 50),
                "llm_median_ms": pct([x["llm_ms"] for x in res if x["llm_calls"]], 50),
                "escalation_rate": mean([x["escalated"] for x in res])
                if config == "escalate"
                else None,
            }
    return out


def mean(xs: list) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def pct(xs: list, q: float) -> float:
    return float(np.percentile(xs, q)) if xs else float("nan")


def bootstrap_ci(rows: list[dict], threshold: float, metric: str) -> dict:
    """記事単位で引き直すブートストラップ。同じ記事のパッセージは独立でないため。"""
    rng = np.random.default_rng(cfg.SEED)
    by_title: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_title[r["title"]].append(r)
    titles = sorted(by_title)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(cfg.BOOTSTRAP_ITERS):
        picked = rng.choice(len(titles), size=len(titles), replace=True)
        rs = [r for i in picked for r in by_title[titles[i]]]
        vals = {}
        for qtype in QUERY_TYPES:
            for config in CONFIGS:
                sub = [
                    config_result(r, config, threshold)[metric]
                    for r in rs
                    if r["qtype"] == qtype
                ]
                vals[f"{qtype}/{config}"] = mean(sub)
        for k, v in vals.items():
            samples[k].append(v)
        for config in CONFIGS:
            samples[f"diff(synthetic-human)/{config}"].append(
                vals[f"synthetic/{config}"] - vals[f"human/{config}"]
            )
    return {k: [pct(v, 2.5), pct(v, 97.5)] for k, v in samples.items()}


def pair_table(rows: list[dict]) -> dict:
    """baseline でのパッセージ単位のペア比較。"""
    by_pid: dict[int, dict] = defaultdict(dict)
    for r in rows:
        by_pid[r["pid"]][r["qtype"]] = r["baseline"]["hit"]
    counts = {"both_hit": 0, "human_only": 0, "synthetic_only": 0, "both_miss": 0}
    for v in by_pid.values():
        h, s = v.get("human", 0), v.get("synthetic", 0)
        key = (
            "both_hit"
            if h and s
            else "human_only"
            if h
            else "synthetic_only"
            if s
            else "both_miss"
        )
        counts[key] += 1
    return counts


def win_loss(rows: list[dict], threshold: float) -> dict:
    """baseline と比べた改善・悪化・変化なしの件数（Recall@5 の当たり外れで判定）。"""
    out = {}
    for qtype in QUERY_TYPES:
        sub = [r for r in rows if r["qtype"] == qtype]
        for config in ("always_expand", "escalate"):
            c = {"improved": 0, "worsened": 0, "unchanged": 0}
            for r in sub:
                d = config_result(r, config, threshold)["hit"] - r["baseline"]["hit"]
                c["improved" if d > 0 else "worsened" if d < 0 else "unchanged"] += 1
            out[f"{qtype}/{config}"] = c
    return out


def ranking(agg: dict, qtype: str, metric: str) -> list[str]:
    """構成を指標の高い順に並べる。同値は "=" でつないで 1 つの順位にする（並び順で優劣を作らない）。"""
    groups: dict[float, list[str]] = defaultdict(list)
    for c in CONFIGS:
        groups[round(agg[f"{qtype}/{c}"][metric], 6)].append(c)
    return [" = ".join(groups[v]) for v in sorted(groups, reverse=True)]


def sweep(rows: list[dict]) -> list[dict]:
    out = []
    for t in cfg.SWEEP_THRESHOLDS:
        for qtype in QUERY_TYPES:
            res = [config_result(r, "escalate", t) for r in rows if r["qtype"] == qtype]
            out.append(
                {
                    "threshold": t,
                    "qtype": qtype,
                    "llm_calls_per_query": mean([x["llm_calls"] for x in res]),
                    "recall_at_5": mean([x["hit"] for x in res]),
                }
            )
    return out


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def run_split(
    pairs: list[Pair], passages_by_pid: dict[int, Passage], index: Index, llm: LLM
) -> list[dict]:
    rows = []
    for i, pair in enumerate(pairs, start=1):
        passage = passages_by_pid[pair.pid]
        syn = llm.synthetic_query(passage.text)
        queries = {"human": pair.human_query, "synthetic": syn["query"]}
        order = (
            list(QUERY_TYPES) if i % 2 else list(reversed(QUERY_TYPES))
        )  # 交互に実行して時間帯の偏りを避ける
        for qtype in order:
            q = queries[qtype]
            r = evaluate_query(index, llm, q, pair.pid)
            rows.append(
                {
                    "split": pair.split,
                    "title": pair.title,
                    "pid": pair.pid,
                    "qtype": qtype,
                    "query": q,
                    **query_features(q, passage.text),
                    **r,
                }
            )
        print(f"  [{pair.split}] {i}/{len(pairs)}", file=sys.stderr)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pairs", type=int, default=5, help="評価用のペア数（5 → 30 → 200）"
    )
    ap.add_argument(
        "--dev-pairs",
        type=int,
        default=None,
        help="開発用のペア数（既定は --pairs と同じ、最大 100）",
    )
    ap.add_argument(
        "--fake",
        action="store_true",
        help="API・ダウンロードなしでロジックだけ確認する",
    )
    args = ap.parse_args()
    dev_n = args.dev_pairs or min(args.pairs, 100)

    passages = load_squad(args.fake)
    by_pid = {p.pid: p for p in passages}
    dev_titles, eval_titles = split_articles(passages)
    print(
        f"コーパス: {len(passages)} パッセージ / {len(dev_titles) + len(eval_titles)} 記事 "
        f"(開発用 {len(dev_titles)} 記事, 評価用 {len(eval_titles)} 記事)",
        file=sys.stderr,
    )

    embedder = Embedder(args.fake)
    embedder.encode(["warm up"] * 4)  # 初回呼び出しの遅さを計測に入れない
    index = Index(embedder, passages)
    llm = LLM(args.fake)

    dev_pairs = sample_pairs(passages, dev_titles, dev_n, "dev")
    eval_pairs = sample_pairs(passages, eval_titles, args.pairs, "eval")
    dev_rows = run_split(dev_pairs, by_pid, index, llm)

    # 閾値は評価用データを見る前に固定する
    threshold_main = choose_threshold(
        [r for r in dev_rows if r["qtype"] == "synthetic"]
    )
    threshold_ref = choose_threshold([r for r in dev_rows if r["qtype"] == "human"])
    print(
        f"閾値（開発用・合成で決定）= {threshold_main} / 参考（開発用・人間で決定）= {threshold_ref}",
        file=sys.stderr,
    )

    eval_rows = run_split(eval_pairs, by_pid, index, llm)
    agg = aggregate(eval_rows, threshold_main)
    summary = {
        "meta": {
            "fake": args.fake,
            "model": cfg.MODEL_ID,
            "temperature": cfg.TEMPERATURE,
            "embed_model": cfg.EMBED_MODEL if not args.fake else "fake-hashing",
            "corpus_passages": len(passages),
            "dev_articles": len(dev_titles),
            "eval_articles": len(eval_titles),
            "dev_pairs": len(dev_pairs),
            "eval_pairs": len(eval_pairs),
            "eval_articles_in_sample": len({p.title for p in eval_pairs}),
            "threshold_main": threshold_main,
            "threshold_ref": threshold_ref,
            "expand_malformed": sum(
                r["expanded"]["malformed"] for r in dev_rows + eval_rows
            ),
            "seed": cfg.SEED,
        },
        "main_threshold": {
            "metrics": agg,
            "ranking": {
                f"{q}/{m}": ranking(agg, q, m)
                for q in QUERY_TYPES
                for m in ("recall_at_5", "mrr_at_5")
            },
            "ci95_recall_at_5": bootstrap_ci(eval_rows, threshold_main, "hit"),
            "ci95_mrr_at_5": bootstrap_ci(eval_rows, threshold_main, "rr"),
            "win_loss_vs_baseline": win_loss(eval_rows, threshold_main),
        },
        "ref_threshold": {
            "metrics": aggregate(eval_rows, threshold_ref),
            "win_loss_vs_baseline": win_loss(eval_rows, threshold_ref),
        },
        "pair_table_baseline": pair_table(eval_rows),
        "sweep": sweep(eval_rows),
        "features_mean": {
            q: {
                k: mean([r[k] for r in eval_rows if r["qtype"] == q])
                for k in (
                    "content_overlap",
                    "query_len_words",
                    "proper_or_number_count",
                )
            }
            for q in QUERY_TYPES
        },
    }

    out_dir = RUNS_DIR / (
        ("fake-" if args.fake else "")
        + f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-pairs{args.pairs}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "queries.jsonl").open("w", encoding="utf-8") as f:
        for r in dev_rows + eval_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "config_snapshot.json").write_text(
        json.dumps(
            {k: v for k, v in vars(cfg).items() if k.isupper()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print_summary(summary)
    print(f"\n出力: {out_dir.relative_to(HERE)}")


def print_summary(s: dict) -> None:
    m = s["meta"]
    print(f"\n# 0008 結果（{'FAKE: 数値に意味はない' if m['fake'] else m['model']}）")
    print(
        f"評価ペア {m['eval_pairs']}（{m['eval_articles_in_sample']} 記事）, コーパス {m['corpus_passages']}, "
        f"閾値 {m['threshold_main']}, 拡張出力の形式崩れ {m['expand_malformed']} 件"
    )
    print(
        "\n| クエリ | 構成 | Recall@5 [95%CI] | MRR@5 [95%CI] | LLM呼出/q | tok/q | 中央値ms | p95ms | 発動率 |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    mt = s["main_threshold"]
    for key, v in mt["metrics"].items():
        q, c = key.split("/")
        ci_r, ci_m = mt["ci95_recall_at_5"][key], mt["ci95_mrr_at_5"][key]
        esc = "" if v["escalation_rate"] is None else f"{v['escalation_rate']:.0%}"
        print(
            f"| {q} | {c} | {v['recall_at_5']:.3f} [{ci_r[0]:.3f}, {ci_r[1]:.3f}] | "
            f"{v['mrr_at_5']:.3f} [{ci_m[0]:.3f}, {ci_m[1]:.3f}] | {v['llm_calls_per_query']:.2f} | "
            f"{v['tokens_per_query']:.0f} | {v['latency_median_ms']:.1f} | {v['latency_p95_ms']:.1f} | {esc} |"
        )
    print("\n構成の順位（主結果）:")
    for k, v in mt["ranking"].items():
        print(f"  {k}: {' > '.join(v)}")
    print(f"ペア比較（baseline）: {s['pair_table_baseline']}")
    print(f"改善・悪化（baseline 比）: {mt['win_loss_vs_baseline']}")
    print(f"クエリ特徴量の平均: {s['features_mean']}")


if __name__ == "__main__":
    main()
