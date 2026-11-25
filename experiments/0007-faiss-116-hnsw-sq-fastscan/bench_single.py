# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0", "faiss-cpu"]
# ///
"""総当たり系の索引を「1 クエリずつ」投げたときのレイテンシを測る。

bench.py は 1,000 クエリを 1 バッチで投げるので、IndexFlatIP は BLAS（行列積）の経路に乗る。
RAG の API は 1 リクエスト 1 クエリが普通なので、その形でも比べる。

    uv run --no-project --with faiss-cpu==1.16.0 --with numpy python bench_single.py --out results/single-1.16.0.json
"""

import argparse
import json
import pathlib
import time
from statistics import median

import faiss
import numpy as np

HERE = pathlib.Path(__file__).parent
K = 10


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--n-query", type=int, default=300)
    parser.add_argument("--trials", type=int, default=3)
    args = parser.parse_args()

    xb = np.load(HERE / "data" / "xb.npy")
    xq = np.load(HERE / "data" / "xq.npy")[: args.n_query]
    d = xb.shape[1]
    faiss.omp_set_num_threads(2)

    indexes = {"flat": faiss.IndexFlatIP(d),
               "sq8": faiss.IndexScalarQuantizer(d, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)}
    if hasattr(faiss, "IndexSQFastScan"):
        indexes["sq_fastscan_8bit"] = faiss.IndexSQFastScan(d, faiss.ScalarQuantizer.QT_8bit, faiss.METRIC_INNER_PRODUCT)
    for idx in indexes.values():
        idx.train(xb)
        idx.add(xb)

    faiss.omp_set_num_threads(1)
    result: dict = {"faiss_version": faiss.__version__, "n_query": len(xq), "trials": args.trials, "indexes": {}}
    for name, idx in indexes.items():
        idx.search(xq[:5], K)
        per_trial_ms = []
        for _ in range(args.trials):
            lat = []
            for i in range(len(xq)):
                t0 = time.perf_counter()
                idx.search(xq[i : i + 1], K)
                lat.append((time.perf_counter() - t0) * 1000)
            per_trial_ms.append(lat)
        p50 = [float(np.percentile(lat, 50)) for lat in per_trial_ms]
        p95 = [float(np.percentile(lat, 95)) for lat in per_trial_ms]
        result["indexes"][name] = {"p50_ms": p50, "p95_ms": p95, "p50_ms_median": median(p50)}
        print(f"  {faiss.__version__} {name}: p50={median(p50):.2f} ms p95={median(p95):.2f} ms", flush=True)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
