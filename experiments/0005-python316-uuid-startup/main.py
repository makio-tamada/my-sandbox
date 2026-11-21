# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Python 3.15.2 と 3.16.0a2 で uuid の速度と起動時間を比べる（まとめ役）。

    uv python install 3.15.2 3.16.0a2
    uv run main.py

各インタプリタで bench_uuid.py / bench_startup.py を実行し、表を標準出力に、
生データを results/ に JSON で保存する。標準ライブラリだけで動く。
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"
VERSIONS = ["3.15.2", "3.16.0a2"]


def find_python(version: str) -> str:
    out = subprocess.run(
        ["uv", "python", "find", version], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def run_json(argv: list[str]) -> dict:
    out = subprocess.run(argv, check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    pythons = {v: find_python(v) for v in VERSIONS}
    for v, p in pythons.items():
        print(f"# {v}: {p}", file=sys.stderr)

    # 1. uuid: 3.15.2（既定）/ 3.16.0a2（既定 = C）/ 3.16.0a2（--pure = 純 Python）
    configs = {
        "3.15.2": [pythons["3.15.2"], str(HERE / "bench_uuid.py")],
        "3.16.0a2 C": [pythons["3.16.0a2"], str(HERE / "bench_uuid.py")],
        "3.16.0a2 純Python": [
            pythons["3.16.0a2"],
            str(HERE / "bench_uuid.py"),
            "--pure",
        ],
    }
    uuid_results = {}
    for name, argv in configs.items():
        print(f"# uuid: {name}", file=sys.stderr)
        uuid_results[name] = run_json(argv)
    (RESULTS / "uuid.json").write_text(
        json.dumps(uuid_results, ensure_ascii=False, indent=2)
    )

    print("## uuid 1 回あたりの時間（ns、7 回の中央値。括弧内は最小〜最大）\n")
    names = list(configs)
    print("| 操作 | " + " | ".join(names) + " | 3.16 C / 3.16 純Py | 3.16 C / 3.15.2 |")
    print("| --- | " + " | ".join("---:" for _ in names) + " | ---: | ---: |")
    for op in uuid_results[names[0]]["ops"]:
        cells = []
        for n in names:
            r = uuid_results[n]["ops"][op]
            cells.append(f"{r['median_ns']:.0f} ({r['min_ns']:.0f}〜{r['max_ns']:.0f})")
        c = uuid_results["3.16.0a2 C"]["ops"][op]["median_ns"]
        pure = uuid_results["3.16.0a2 純Python"]["ops"][op]["median_ns"]
        old = uuid_results["3.15.2"]["ops"][op]["median_ns"]
        print(
            f"| {op} | " + " | ".join(cells) + f" | {pure / c:.2f}x | {old / c:.2f}x |"
        )

    print("\n## 正しさの確認\n")
    for n in names:
        r = uuid_results[n]
        print(
            f"- {n}（uuid4 実装: {r['uuid4_impl']}, UUID クラス: {r['uuid_class_module']}）: {r['checks']}"
        )

    # 2. 互換性（クラッシュしても続けられるよう項目ごとに子プロセスで実行）
    print("# compat", file=sys.stderr)
    compat = run_json(
        [sys.executable, str(HERE / "check_compat.py"), *pythons.values()]
    )
    (RESULTS / "compat.json").write_text(
        json.dumps(compat, ensure_ascii=False, indent=2)
    )
    print("\n## 互換性の確認\n")
    print("| 項目 | " + " | ".join(VERSIONS) + " |")
    print("| --- | " + " | ".join("---" for _ in VERSIONS) + " |")
    for name, per_py in compat.items():
        print(
            f"| {name} | "
            + " | ".join(per_py[pythons[v]]["outcome"] for v in VERSIONS)
            + " |"
        )

    # 3. 起動時間
    print("\n# startup", file=sys.stderr)
    startup = run_json(
        [sys.executable, str(HERE / "bench_startup.py"), *pythons.values()]
    )
    (RESULTS / "startup.json").write_text(
        json.dumps(startup, ensure_ascii=False, indent=2)
    )
    print("\n## 起動時間（ms、200 回の中央値。括弧内は p10〜p90）\n")
    print("| コマンド | " + " | ".join(VERSIONS) + " | 差（3.16 − 3.15） |")
    print("| --- | " + " | ".join("---:" for _ in VERSIONS) + " | ---: |")
    for label, per_py in startup.items():
        rows = [per_py[pythons[v]] for v in VERSIONS]
        cells = [
            f"{r['median_ms']:.2f} ({r['p10_ms']:.2f}〜{r['p90_ms']:.2f})" for r in rows
        ]
        diff = rows[1]["median_ms"] - rows[0]["median_ms"]
        pct = diff / rows[0]["median_ms"] * 100
        print(
            f"| `{label}` | " + " | ".join(cells) + f" | {diff:+.2f} ms ({pct:+.1f}%) |"
        )


if __name__ == "__main__":
    main()
