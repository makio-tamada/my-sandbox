# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0", "faiss-cpu"]
# ///
"""HNSW を粗量子化器に使う IVF で、1.16.0 のシンク除去リンクの効果を測る。

faiss 1.16.0 の docstring では、シンク除去リンク（add_level_0_links_from_sample）は
「HNSW を IVF の粗量子化器にしたときに efSearch が小さいとリストが偏る」ことへの対策で、
IndexIVF::train から自動で呼ばれる、とされている。単体の IndexHNSWFlat では自動で入らない。

    uv run --no-project --with faiss-cpu==1.16.0 --with numpy python bench_ivf.py --out results/ivf-1.16.0.json

計測の約束は bench.py と同じ（検索は 1 スレッド・5 回の中央値、recall@10 は総当たりが正解）。
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


def recall_at_k(found: np.ndarray, truth: np.ndarray) -> float:
    hits = sum(len(set(f[:K]) & set(t[:K])) for f, t in zip(found, truth))
    return hits / (len(truth) * K)


def list_sizes(ivf) -> np.ndarray:
    invlists = ivf.invlists
    return np.array([invlists.list_size(i) for i in range(ivf.nlist)])


def run(xb, xq, truth, *, nlist, quantizer_ef, nprobe_list, trials, samples_per_node) -> dict:
    d = xb.shape[1]
    quantizer = faiss.IndexHNSWFlat(d, 32, faiss.METRIC_INNER_PRODUCT)
    info: dict = {"nlist": nlist, "quantizer_efSearch": quantizer_ef}
    if hasattr(quantizer, "level_0_link_samples_per_node"):
        info["level_0_link_samples_per_node_default"] = int(quantizer.level_0_link_samples_per_node)
        if samples_per_node is not None:
            quantizer.level_0_link_samples_per_node = samples_per_node
        info["level_0_link_samples_per_node"] = int(quantizer.level_0_link_samples_per_node)
    ivf = faiss.IndexIVFFlat(quantizer, d, nlist, faiss.METRIC_INNER_PRODUCT)
    ivf.cp.seed = 1234
    faiss.omp_set_num_threads(2)
    t0 = time.perf_counter()
    ivf.train(xb)
    info["seconds_train"] = time.perf_counter() - t0
    # add のときの割り当ても quantizer の efSearch で決まる
    quantizer.hnsw.efSearch = quantizer_ef
    t0 = time.perf_counter()
    ivf.add(xb)
    info["seconds_add"] = time.perf_counter() - t0
    sizes = list_sizes(ivf)
    info["list_size"] = {
        "max": int(sizes.max()),
        "p99": float(np.percentile(sizes, 99)),
        "empty_lists": int((sizes == 0).sum()),
        "imbalance_factor": float(ivf.invlists.imbalance_factor()),
    }
    # 量子化器の割り当てがどれだけ正確か: 総当たりで最も近い重心と一致する割合
    centroids = quantizer.storage.reconstruct_n(0, nlist) if hasattr(quantizer, "storage") else None
    if centroids is not None:
        exact = faiss.IndexFlatIP(d)
        exact.add(centroids)
        _, exact_assign = exact.search(xb, 1)
        _, hnsw_assign = quantizer.search(xb, 1)
        info["assign_accuracy"] = float((exact_assign[:, 0] == hnsw_assign[:, 0]).mean())
    info["search"] = []
    faiss.omp_set_num_threads(1)
    for nprobe in nprobe_list:
        ivf.nprobe = nprobe
        ivf.search(xq, K)
        durations = []
        for _ in range(trials):
            t0 = time.perf_counter()
            _, labels = ivf.search(xq, K)
            durations.append(time.perf_counter() - t0)
        med = median(durations)
        row = {"nprobe": nprobe, "qps": len(xq) / med, "seconds_median": med, "recall_at_10": recall_at_k(labels, truth)}
        info["search"].append(row)
        print(f"  IVF{nlist}[samples={info.get('level_0_link_samples_per_node')}] nprobe={nprobe} "
              f"recall@10={row['recall_at_10']:.4f} qps={row['qps']:.0f}", flush=True)
    print(f"  lists: {info['list_size']} assign_acc={info.get('assign_accuracy')}", flush=True)
    return info


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--nlist", type=int, default=4096)
    parser.add_argument("--quantizer-ef", type=int, default=8)
    parser.add_argument("--nprobe", type=int, nargs="+", default=[4, 16, 64])
    parser.add_argument("--trials", type=int, default=5)
    args = parser.parse_args()

    data = HERE / "data"
    xb = np.load(data / "xb.npy")
    xq = np.load(data / "xq.npy")
    d = xb.shape[1]
    flat = faiss.IndexFlatIP(d)
    flat.add(xb)
    faiss.omp_set_num_threads(2)
    _, truth = flat.search(xq, K)

    result: dict = {"faiss_version": faiss.__version__, "runs": []}
    print(f"faiss {faiss.__version__}", flush=True)
    variants = [None]
    if hasattr(faiss.IndexHNSW, "level_0_link_samples_per_node"):
        variants.append(0)  # シンク除去リンクを切った対照
    for v in variants:
        result["runs"].append(run(xb, xq, truth, nlist=args.nlist, quantizer_ef=args.quantizer_ef,
                                  nprobe_list=args.nprobe, trials=args.trials, samples_per_node=v))
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
