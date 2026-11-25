# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0", "faiss-cpu"]
# ///
"""faiss の 1 バージョンについて HNSW / SQ8 / SQFastScan を計測し、JSON に書く。

バージョンは実行時に入っている faiss-cpu で決まる。main.py が版ごとに次の形で呼ぶ。

    uv run --no-project --with faiss-cpu==1.16.0 --with numpy python bench.py --out results/faiss-1.16.0.json

計測の約束:
- 検索の QPS は omp_set_num_threads(1) で 1,000 クエリを 1 回のバッチで投げ、5 回の中央値
  （SQ8 / Flat は 2 スレッドでも測る）
- recall@10 は IndexFlatIP の上位 10 件を正解とした一致率の平均
- HNSW の構築は 2 スレッド
"""

import argparse
import json
import pathlib
import platform
import time
from statistics import median

import faiss
import numpy as np

HERE = pathlib.Path(__file__).parent
K = 10


def timed(func, trials: int) -> tuple[list[float], object]:
    """func を 1 回空回ししてから trials 回測り、所要秒のリストと最後の戻り値を返す。"""
    result = func()
    durations = []
    for _ in range(trials):
        t0 = time.perf_counter()
        result = func()
        durations.append(time.perf_counter() - t0)
    return durations, result


def recall_at_k(found: np.ndarray, truth: np.ndarray) -> float:
    hits = sum(len(set(f[:K]) & set(t[:K])) for f, t in zip(found, truth))
    return hits / (len(truth) * K)


def search_stats(index, xq, truth, trials: int, threads: int) -> dict:
    faiss.omp_set_num_threads(threads)
    durations, (_, labels) = timed(lambda: index.search(xq, K), trials)
    med = median(durations)
    return {
        "threads": threads,
        "seconds_median": med,
        "seconds_min": min(durations),
        "seconds_max": max(durations),
        "qps": len(xq) / med,
        "recall_at_10": recall_at_k(labels, truth),
    }


def index_bytes(index) -> int:
    return int(faiss.serialize_index(index).size)


def bench_hnsw(xb, xq, xt, truth, trials, ef_list, *, M, ef_construction, mode) -> dict:
    """mode: plain = add だけ / samples0 = level_0_link_samples_per_node=0 で add /
    sample_links = add の後に add_level_0_links_from_sample(xt) を呼ぶ"""
    d = xb.shape[1]
    index = faiss.IndexHNSWFlat(d, M, faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = ef_construction
    info: dict = {"mode": mode, "M": M, "efConstruction": ef_construction}
    if hasattr(index, "level_0_link_samples_per_node"):
        info["level_0_link_samples_per_node_default"] = int(index.level_0_link_samples_per_node)
        if mode == "samples0":
            index.level_0_link_samples_per_node = 0
    faiss.omp_set_num_threads(2)
    t0 = time.perf_counter()
    index.add(xb)
    info["seconds_add"] = time.perf_counter() - t0
    if mode == "sample_links":
        t0 = time.perf_counter()
        stats = index.add_level_0_links_from_sample(xt)
        info["seconds_sample_links"] = time.perf_counter() - t0
        info["sample_link_stats"] = {
            name: int(getattr(stats, name))
            for name in ("n_rounds", "n_sinks_found", "n_sinks_remaining", "n_links_added", "n_links_replaced", "n_exact_searches")
            if hasattr(stats, name)
        }
    info["index_bytes"] = index_bytes(index)
    info["search"] = []
    for ef in ef_list:
        index.hnsw.efSearch = ef
        row = search_stats(index, xq, truth, trials, threads=1)
        row["efSearch"] = ef
        info["search"].append(row)
        print(f"  HNSW[{mode}] ef={ef:4d} recall@10={row['recall_at_10']:.4f} qps={row['qps']:.0f}", flush=True)
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--hnsw-m", type=int, default=32)
    parser.add_argument("--ef-construction", type=int, default=200)
    parser.add_argument("--ef", type=int, nargs="+", default=[16, 32, 64, 128])
    args = parser.parse_args()

    data = HERE / "data"
    xb = np.load(data / "xb.npy")
    xq = np.load(data / "xq.npy")
    xt = np.load(data / "xt.npy")
    d = xb.shape[1]
    result: dict = {
        "faiss_version": faiss.__version__,
        "compile_options": faiss.get_compile_options(),
        "python": platform.python_version(),
        "n_base": int(xb.shape[0]),
        "n_query": int(xq.shape[0]),
        "dim": d,
        "trials": args.trials,
    }
    print(f"faiss {faiss.__version__} / {result['compile_options']}", flush=True)

    # 正解: 総当たり
    flat = faiss.IndexFlatIP(d)
    flat.add(xb)
    faiss.omp_set_num_threads(2)
    _, truth = flat.search(xq, K)
    result["flat"] = [search_stats(flat, xq, truth, args.trials, threads=t) for t in (1, 2)]
    result["flat_index_bytes"] = index_bytes(flat)
    print(f"  Flat qps(1t)={result['flat'][0]['qps']:.0f}", flush=True)

    # SQ8 総当たり（#5829 の x86 8bit 内積の高速化）
    sq8 = faiss.IndexScalarQuantizer(d, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)
    faiss.omp_set_num_threads(2)
    sq8.train(xb)
    sq8.add(xb)
    result["sq8"] = [search_stats(sq8, xq, truth, args.trials, threads=t) for t in (1, 2)]
    result["sq8_index_bytes"] = index_bytes(sq8)
    print(f"  SQ8 qps(1t)={result['sq8'][0]['qps']:.0f} recall={result['sq8'][0]['recall_at_10']:.4f}", flush=True)

    # SQFastScan（1.16.0 で追加）
    if hasattr(faiss, "IndexSQFastScan"):
        result["sq_fastscan"] = []
        for qname in ("QT_8bit", "QT_4bit"):
            qtype = getattr(faiss.ScalarQuantizer, qname)
            idx = faiss.IndexSQFastScan(d, qtype, faiss.METRIC_INNER_PRODUCT)
            faiss.omp_set_num_threads(2)
            t0 = time.perf_counter()
            idx.train(xb)
            idx.add(xb)
            build = time.perf_counter() - t0
            default_rerank = int(idx.rerank_factor) if hasattr(idx, "rerank_factor") else None
            rerank_values = [default_rerank] if qname == "QT_4bit" else sorted({default_rerank, 1, 2, 4, 8} - {None})
            for rf in rerank_values:
                if rf is not None and hasattr(idx, "rerank_factor"):
                    idx.rerank_factor = rf
                for t in (1, 2):
                    row = search_stats(idx, xq, truth, args.trials, threads=t)
                    row.update({"qtype": qname, "rerank_factor": rf, "rerank_factor_default": default_rerank,
                                "seconds_build": build, "index_bytes": index_bytes(idx)})
                    result["sq_fastscan"].append(row)
                    print(f"  SQFastScan[{qname} rf={rf}] {t}t recall={row['recall_at_10']:.4f} qps={row['qps']:.0f} bytes={row['index_bytes']:,}", flush=True)
    else:
        result["sq_fastscan"] = None

    # HNSW
    modes = ["plain"]
    if hasattr(faiss.IndexHNSW, "level_0_link_samples_per_node"):
        modes += ["samples0", "sample_links"]
    result["hnsw"] = [
        bench_hnsw(xb, xq, xt, truth, args.trials, args.ef, M=args.hnsw_m, ef_construction=args.ef_construction, mode=m)
        for m in modes
    ]

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
