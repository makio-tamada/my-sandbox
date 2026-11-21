"""1 プロセスで 1 回だけ JSON を読み、RSS と処理時間を測る（計測される側）。

    <venv>/bin/python measure.py --payload payload.json --mode root_dict

main.py から版ごとの仮想環境の python で呼ばれる。結果は JSON 1 行で標準出力に出す。
ペイロードはファイルから bytes で読むだけにして、計測前のピーク RSS を小さく保つ。
"""

import argparse
import ctypes
import gc
import json
import os
import resource
import sys
import time
from pathlib import Path

import pydantic
import pydantic_core
from pydantic import BaseModel, RootModel

PAGE = os.sysconf("SC_PAGE_SIZE")


class Plain(RootModel[dict[str, object]]):
    """pydantic#14234 の再現コードと同じ形（中身を型付けしない）。"""


class Kind(BaseModel):
    name: str
    version: str


class Item(BaseModel):
    id: str
    kind: Kind
    attributes: dict[str, str]


class Typed(BaseModel):
    items: list[Item]


def rss_now_mb() -> float:
    """いまの RSS（/proc/self/statm の 2 列目）。"""
    with open("/proc/self/statm") as f:
        return int(f.read().split()[1]) * PAGE / 1024**2


def rss_peak_mb() -> float:
    """プロセス開始からのピーク RSS（Linux の ru_maxrss は KiB）。"""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def reset_hwm() -> None:
    """VmHWM（ピーク RSS）をいまの RSS に戻す（Linux 4.0 以降の clear_refs）。"""
    with open("/proc/self/clear_refs", "w") as f:
        f.write("5")


def hwm_mb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmHWM not found")


def parse(mode: str, data: bytes) -> object:
    if mode == "root_dict":
        return Plain.model_validate_json(data)
    if mode == "typed":
        return Typed.model_validate_json(data)
    if mode == "from_json":
        return pydantic_core.from_json(data)
    raise ValueError(mode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument(
        "--mode", choices=["root_dict", "typed", "from_json"], required=True
    )
    args = parser.parse_args()

    data = args.payload.read_bytes()
    gc.collect()
    base_now, base_peak = rss_now_mb(), rss_peak_mb()
    reset_hwm()

    start = time.perf_counter()
    result = parse(args.mode, data)
    elapsed = time.perf_counter() - start

    hwm = hwm_mb()
    gc.collect()
    peak = rss_peak_mb()
    with_result = rss_now_mb()
    del result
    gc.collect()
    after_del = rss_now_mb()
    ctypes.CDLL("libc.so.6").malloc_trim(
        0
    )  # glibc が抱えている空き領域を OS に返させる
    after_trim = rss_now_mb()

    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "pydantic": pydantic.VERSION,
                "pydantic_core": pydantic_core.__version__,
                "mode": args.mode,
                "payload_mb": len(data) / 1e6,
                "seconds": elapsed,
                "peak_delta_mb": peak
                - base_peak,  # 元の報告の retained_after_validate と同じ量
                "hwm_delta_mb": hwm
                - base_now,  # 直前に VmHWM を戻してから測ったピーク増分
                "base_peak_mb": base_peak,
                "held_with_result_mb": with_result
                - base_now,  # 結果を持っている間の増分
                "left_after_trim_mb": after_trim
                - base_now,  # さらに malloc_trim(0) した後
                "left_after_del_mb": after_del
                - base_now,  # 結果を捨てて gc した後に残る増分
            }
        )
    )


if __name__ == "__main__":
    main()
