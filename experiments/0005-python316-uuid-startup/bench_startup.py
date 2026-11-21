"""複数のインタプリタの起動時間を、交互に subprocess で起動して計測する。

    python3 bench_startup.py /path/to/python3.15 /path/to/python3.16 --runs 200

各コマンドについてインタプリタを交互に起動し（順番による偏りを減らす）、
起動から終了までの壁時計時間を perf_counter で測る。結果は JSON で標準出力に出す。
"""

import argparse
import json
import subprocess
import time
from statistics import median, quantiles

COMMANDS = {
    "-I -c pass": ["-I", "-c", "pass"],
    "-c pass（site あり）": ["-c", "pass"],
    "-I -c 'import 標準 6 モジュール'": [
        "-I",
        "-c",
        "import json, re, pathlib, dataclasses, typing, uuid",
    ],
}


def run_once(python: str, argv: list[str]) -> float:
    start = time.perf_counter()
    subprocess.run(
        [python, *argv],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pythons", nargs="+")
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--warmup", type=int, default=10)
    args = parser.parse_args()

    results: dict[str, dict[str, dict[str, float]]] = {}
    for label, argv in COMMANDS.items():
        samples: dict[str, list[float]] = {p: [] for p in args.pythons}
        for _ in range(args.warmup):
            for p in args.pythons:
                run_once(p, argv)
        for _ in range(args.runs):
            for p in args.pythons:
                samples[p].append(run_once(p, argv) * 1000)
        results[label] = {}
        for p, xs in samples.items():
            q = quantiles(xs, n=10)
            results[label][p] = {
                "median_ms": median(xs),
                "p10_ms": q[0],
                "p90_ms": q[-1],
                "runs": len(xs),
            }
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
