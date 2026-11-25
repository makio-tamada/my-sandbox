"""results/*.json から Markdown の表を作る（標準ライブラリだけで動く）。

    python3 summarize.py > results/summary.md

同じ版の結果が複数あるとき（faiss-1.16.0.json と faiss-1.16.0.run2.json など）は、
QPS は各回の値を「/」で並べ、recall は 1 回目の値を出す（recall は回をまたいで同じになる）。
"""

import json
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results"


def load_bench() -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(RESULTS.glob("faiss-*.json")):
        data = json.loads(path.read_text())
        runs[data["faiss_version"]].append(data)
    return dict(sorted(runs.items()))


def qps_list(values: list[float]) -> str:
    return " / ".join(f"{v:,.0f}" for v in values)


def main() -> None:
    bench = load_bench()
    versions = list(bench)
    print("## 総当たり（1,000 クエリを 1 バッチ、5 回の中央値）\n")
    print("| 版 | 索引 | スレッド | QPS（回ごと） | recall@10 | 索引サイズ |")
    print("| --- | --- | --: | --: | --: | --: |")
    for v in versions:
        runs = bench[v]
        for key, size_key in (("flat", "flat_index_bytes"), ("sq8", "sq8_index_bytes")):
            for i, row in enumerate(runs[0][key]):
                qps = [r[key][i]["qps"] for r in runs]
                print(f"| {v} | {key} | {row['threads']} | {qps_list(qps)} | {row['recall_at_10']:.4f} "
                      f"| {runs[0][size_key] / 1e6:.1f} MB |")

    print("\n## IndexSQFastScan（1.16.0 のみ）\n")
    print("| qtype | rerank_factor | スレッド | QPS（回ごと） | recall@10 | 索引サイズ |")
    print("| --- | --: | --: | --: | --: | --: |")
    for v in versions:
        runs = bench[v]
        if not runs[0].get("sq_fastscan"):
            continue
        for i, row in enumerate(runs[0]["sq_fastscan"]):
            qps = [r["sq_fastscan"][i]["qps"] for r in runs]
            mark = "（既定）" if row["rerank_factor"] == row["rerank_factor_default"] else ""
            print(f"| {row['qtype']} | {row['rerank_factor']}{mark} | {row['threads']} | {qps_list(qps)} "
                  f"| {row['recall_at_10']:.4f} | {row['index_bytes'] / 1e6:.1f} MB |")

    print("\n## HNSW（M=32, efConstruction=200。検索は 1 スレッド、構築は 2 スレッド）\n")
    print("| 版 | モード | 構築秒（回ごと） | efSearch | recall@10 | QPS（回ごと） |")
    print("| --- | --- | --: | --: | --: | --: |")
    for v in versions:
        runs = bench[v]
        for m, h in enumerate(runs[0]["hnsw"]):
            build = [r["hnsw"][m]["seconds_add"] + r["hnsw"][m].get("seconds_sample_links", 0.0) for r in runs]
            for j, row in enumerate(h["search"]):
                qps = [r["hnsw"][m]["search"][j]["qps"] for r in runs]
                b = " / ".join(f"{x:.1f}" for x in build) if j == 0 else ""
                print(f"| {v} | {h['mode']} | {b} | {row['efSearch']} | {row['recall_at_10']:.4f} | {qps_list(qps)} |")
    for v in versions:
        for h in bench[v][0]["hnsw"]:
            if "sample_link_stats" in h:
                print(f"\n{v} の add_level_0_links_from_sample(xt) の統計: `{h['sample_link_stats']}`"
                      f"（{h['seconds_sample_links']:.1f} 秒）")

    print("\n## IVF4096 + HNSW 粗量子化器（量子化器 efSearch=8。検索は 1 スレッド）\n")
    print("| 版 | samples_per_node | 学習秒 | 重心割り当て正答率 | 最大リスト長 | 偏り係数 | nprobe | recall@10 | QPS |")
    print("| --- | --: | --: | --: | --: | --: | --: | --: | --: |")
    for path in sorted(RESULTS.glob("ivf-*.json")):
        data = json.loads(path.read_text())
        for run in data["runs"]:
            for j, row in enumerate(run["search"]):
                head = (f"{run['seconds_train']:.1f} | {run['assign_accuracy']:.4f} | {run['list_size']['max']} "
                        f"| {run['list_size']['imbalance_factor']:.4f}") if j == 0 else " |  |  | "
                print(f"| {data['faiss_version']} | {run.get('level_0_link_samples_per_node', '-')} | {head} "
                      f"| {row['nprobe']} | {row['recall_at_10']:.4f} | {row['qps']:,.0f} |")

    print("\n## 1 クエリずつ投げたときのレイテンシ（1 スレッド、300 クエリ、3 回）\n")
    print("| 版 | 索引 | p50（回ごと, ms） | p95（回ごと, ms） |")
    print("| --- | --- | --: | --: |")
    for path in sorted(RESULTS.glob("single-*.json")):
        data = json.loads(path.read_text())
        for name, row in data["indexes"].items():
            p50 = " / ".join(f"{x:.2f}" for x in row["p50_ms"])
            p95 = " / ".join(f"{x:.2f}" for x in row["p95_ms"])
            print(f"| {data['faiss_version']} | {name} | {p50} | {p95} |")


if __name__ == "__main__":
    main()
