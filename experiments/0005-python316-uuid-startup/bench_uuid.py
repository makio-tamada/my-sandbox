"""uuid の生成・構築・文字列化を計測し、正しさも確かめる（比較したいインタプリタで直接実行する）。

    python3.16 bench_uuid.py          # 既定の実装（3.16 なら C 実装）
    python3.16 bench_uuid.py --pure   # _uuid を無効化して純 Python フォールバックを使う

結果は JSON で標準出力に出す。標準ライブラリだけで動く。
"""

import argparse
import itertools
import json
import sys
import timeit
from statistics import median

parser = argparse.ArgumentParser()
parser.add_argument(
    "--pure", action="store_true", help="_uuid を無効化して純 Python 実装を使う"
)
parser.add_argument("--repeat", type=int, default=7)
parser.add_argument("--check-n", type=int, default=1_000_000)
args = parser.parse_args()

if args.pure:
    # import uuid より前に塞ぐと、uuid.py の try/except ImportError で純 Python 版に落ちる
    sys.modules["_uuid"] = None  # type: ignore[assignment]

import uuid

SAMPLE_STR = "6f2c1e0a-3b4d-4c5e-8f60-718293a4b5c6"
SAMPLE_BYTES = bytes.fromhex(SAMPLE_STR.replace("-", ""))
SAMPLE = uuid.UUID(SAMPLE_STR)

OPERATIONS = {
    "uuid4()": "uuid4()",
    "uuid7()": "uuid7()",
    "UUID(str)": "UUID(s)",
    "UUID(bytes=)": "UUID(bytes=b)",
    "str(UUID)": "str(u)",
}


def bench(stmt: str) -> dict[str, float]:
    """1 回あたりのナノ秒を repeat 回計測し、中央値・最小・最大を返す。"""
    env = {
        "uuid4": uuid.uuid4,
        "uuid7": uuid.uuid7,
        "UUID": uuid.UUID,
        "s": SAMPLE_STR,
        "b": SAMPLE_BYTES,
        "u": SAMPLE,
    }
    timer = timeit.Timer(stmt, globals=env)
    number, _ = (
        timer.autorange()
    )  # 0.2 秒以上かかる回数を決める（ウォームアップを兼ねる）
    number *= 2
    per_call = [
        t / number * 1e9 for t in timer.repeat(repeat=args.repeat, number=number)
    ]
    return {
        "median_ns": median(per_call),
        "min_ns": min(per_call),
        "max_ns": max(per_call),
        "number": number,
    }


def check(n: int) -> dict[str, object]:
    """生成結果の version / variant、一意性、uuid7 の単調増加、往復変換を確かめる。"""
    v4 = [uuid.uuid4() for _ in range(n)]
    v7 = [uuid.uuid7() for _ in range(n)]
    ints7 = [u.int for u in v7]
    roundtrip = all(
        uuid.UUID(str(u)) == u and uuid.UUID(bytes=u.bytes) == u for u in v4[:10_000]
    )
    result: dict[str, object] = {
        "uuid4_all_version4": all(u.version == 4 for u in v4),
        "uuid4_all_rfc_variant": all(u.variant == uuid.RFC_4122 for u in v4),
        "uuid4_unique": len({u.int for u in v4}) == n,
        "uuid7_all_version7": all(u.version == 7 for u in v7),
        "uuid7_strictly_increasing": all(a < b for a, b in itertools.pairwise(ints7)),
        "uuid7_unique": len(set(ints7)) == n,
        "roundtrip_str_bytes": roundtrip,
    }
    # C 実装があるときは、純 Python 版のクラス（uuid._py_UUID）と値・等価・ハッシュが一致するか
    py_uuid = getattr(uuid, "_py_UUID", None)
    if py_uuid is not None and py_uuid is not uuid.UUID:
        c_obj, py_obj = uuid.UUID(SAMPLE_STR), py_uuid(SAMPLE_STR)
        result["c_vs_py_same_int"] = c_obj.int == py_obj.int
        result["c_vs_py_same_str"] = str(c_obj) == str(py_obj)
        result["c_vs_py_eq"] = c_obj == py_obj
        result["c_vs_py_same_hash"] = hash(c_obj) == hash(py_obj)
    return result


def main() -> None:
    impl = type(uuid.uuid4).__name__  # 'builtin_function_or_method' なら C 実装
    out = {
        "python": sys.version.split()[0],
        "mode": "pure" if args.pure else "default",
        "uuid4_impl": "C" if impl == "builtin_function_or_method" else "Python",
        "uuid_class_module": uuid.UUID.__module__,
        "ops": {name: bench(stmt) for name, stmt in OPERATIONS.items()},
        "checks": check(args.check_n),
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
