# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""pydantic 2.14.1〜2.14.4 で model_validate_json のメモリと時間を比べる（まとめ役）。

    uv run main.py

1. 版ごとに .venvs/<版>/ を uv で作る（Python 3.14）
2. pydantic#14234 の再現コードと同じ形の JSON（既定 10 万件 × 属性 30、約 47 MB）を payload.json に書く
3. 各版 × 各モード（root_dict / typed / from_json）を別プロセスで --runs 回ずつ、版を交互に計測する
4. 中央値の表を標準出力に、生データを results/raw.json に保存する
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from statistics import median

HERE = Path(__file__).parent
VENVS = HERE / ".venvs"
RESULTS = HERE / "results"
VERSIONS = ["2.14.1", "2.14.2", "2.14.3", "2.14.4"]
MODES = ["root_dict", "typed", "from_json"]
PYTHON = "3.14"


def ensure_venv(version: str) -> Path:
    venv = VENVS / version
    py = venv / "bin" / "python"
    if not py.exists():
        subprocess.run(["uv", "venv", "-q", "--python", PYTHON, str(venv)], check=True)
        subprocess.run(
            ["uv", "pip", "install", "-q", "--python", str(py), f"pydantic=={version}"],
            check=True,
        )
    return py


def build_payload(path: Path, n_obj: int, n_attrs: int) -> None:
    """pydantic#14234 の build_payload と同じ構造。"""
    items = [
        {
            "id": f"/objects/{i:07d}",
            "kind": {"name": "thing", "version": "1.0.0"},
            "attributes": {f"key{j}": "" for j in range(n_attrs)},
        }
        for i in range(n_obj)
    ]
    path.write_text(json.dumps({"items": items}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--n-obj", type=int, default=100_000)
    parser.add_argument("--n-attrs", type=int, default=30)
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    pythons = {v: ensure_venv(v) for v in VERSIONS}
    payload = VENVS / "payload.json"
    build_payload(payload, args.n_obj, args.n_attrs)

    raw: list[dict] = []
    for mode in MODES:
        for run in range(args.runs):
            for v in VERSIONS:  # 版を交互に回して、時間による偏りを減らす
                out = subprocess.run(
                    [
                        str(pythons[v]),
                        str(HERE / "measure.py"),
                        "--payload",
                        str(payload),
                        "--mode",
                        mode,
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                rec = json.loads(out.stdout) | {"run": run}
                raw.append(rec)
                print(
                    f"# {mode} run{run} {v}: peak+{rec['peak_delta_mb']:.0f}MB {rec['seconds']:.2f}s",
                    file=sys.stderr,
                )
    (RESULTS / "raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2))

    first = raw[0]
    print(
        f"Python {first['python']} / JSON {first['payload_mb']:.1f} MB / 各 {args.runs} 回の中央値（括弧内は最小〜最大）\n"
    )
    metrics = [
        ("hwm_delta_mb", "ピーク RSS 増分 (MB、VmHWM)"),
        ("peak_delta_mb", "ru_maxrss の増分 (MB、元の報告と同じ量)"),
        ("held_with_result_mb", "結果保持中の RSS 増分 (MB)"),
        ("left_after_del_mb", "結果を捨てた後に残る RSS 増分 (MB)"),
        ("left_after_trim_mb", "さらに malloc_trim(0) 後に残る RSS 増分 (MB)"),
        ("seconds", "処理時間 (秒)"),
    ]
    for mode in MODES:
        print(f"## {mode}\n")
        print(
            "| 指標 | "
            + " | ".join(f"{v} (core {_core(raw, v)})" for v in VERSIONS)
            + " |"
        )
        print("| --- | " + " | ".join("---:" for _ in VERSIONS) + " |")
        for key, label in metrics:
            cells = []
            for v in VERSIONS:
                xs = [r[key] for r in raw if r["mode"] == mode and r["pydantic"] == v]
                fmt = "{:.2f}" if key == "seconds" else "{:.0f}"
                cells.append(
                    f"{fmt.format(median(xs))} ({fmt.format(min(xs))}〜{fmt.format(max(xs))})"
                )
            print(f"| {label} | " + " | ".join(cells) + " |")
        print()


def _core(raw: list[dict], version: str) -> str:
    return next(r["pydantic_core"] for r in raw if r["pydantic"] == version)


if __name__ == "__main__":
    main()
