# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""単発の技術検証スクリプト。

依存は上のインラインメタデータ（PEP 723）に書く。仮想環境を作らずに次で実行できる。

    uv run main.py

依存の追加は `uv add --script main.py <package>`。
"""

import time
from statistics import median


def measure(func, *, trials: int = 5, warmup: int = 1) -> dict[str, float]:
    """func を warmup 回空回ししてから trials 回計測し、中央値と最小・最大を返す。

    1 回きりの計測を結論にしないための最低限の型。
    """
    for _ in range(warmup):
        func()

    durations = []
    for _ in range(trials):
        start = time.perf_counter()
        func()
        durations.append(time.perf_counter() - start)

    return {
        "median": median(durations),
        "min": min(durations),
        "max": max(durations),
    }


def main() -> None:
    # ここに検証したい処理を書く
    result = measure(lambda: sum(range(1_000_000)))
    print(f"中央値: {result['median']:.4f} 秒 （最小 {result['min']:.4f} / 最大 {result['max']:.4f}）")


if __name__ == "__main__":
    main()
