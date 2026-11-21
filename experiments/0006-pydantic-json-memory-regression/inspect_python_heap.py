"""結果の Python オブジェクトが使うメモリを tracemalloc と sys.getsizeof で数える。

    <venv>/bin/python inspect_python_heap.py --payload payload.json

版ごとの RSS の差が「Python オブジェクトの量の差」なのか「それ以外」なのかを切り分けるために使う。
"""

import argparse
import json
import sys
import tracemalloc
from pathlib import Path

import pydantic
from pydantic import RootModel


class Plain(RootModel[dict[str, object]]):
    pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    data = args.payload.read_bytes()

    tracemalloc.start()
    items = Plain.model_validate_json(data).root["items"]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    getsizeof_total = sum(
        sys.getsizeof(it)
        + sys.getsizeof(it["id"])
        + sys.getsizeof(it["kind"])
        + sys.getsizeof(it["attributes"])
        + sum(sys.getsizeof(k) for k in it["attributes"])
        for it in items
    )
    print(
        json.dumps(
            {
                "pydantic": pydantic.VERSION,
                "tracemalloc_current_mb": current / 1e6,
                "tracemalloc_peak_mb": peak / 1e6,
                "getsizeof_items_mb": getsizeof_total / 1e6,
            }
        )
    )


if __name__ == "__main__":
    main()
