"""SET LOCAL をトランザクションで囲むオーバーヘッドを、素の SELECT と比較して p50/p95 で測る。"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

import asyncpg
import numpy as np

from .pool_factories import DSN, EF_SEARCH

N_QUERIES = 200
DATA_DIR = Path(__file__).resolve().parent.parent / ".data"


def _vec_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


async def _plain_select(conn: asyncpg.Connection, vec_str: str) -> float:
    t0 = time.perf_counter()
    await conn.fetch(f"SELECT id FROM docs ORDER BY embedding <=> '{vec_str}' LIMIT 10")
    return (time.perf_counter() - t0) * 1000


async def _set_local_select(conn: asyncpg.Connection, vec_str: str) -> float:
    t0 = time.perf_counter()
    async with conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}")
        await conn.fetch(f"SELECT id FROM docs ORDER BY embedding <=> '{vec_str}' LIMIT 10")
    return (time.perf_counter() - t0) * 1000


def _percentile(values: list[float], p: float) -> float:
    return round(float(np.percentile(values, p)), 3)


async def main() -> dict:
    queries = np.load(DATA_DIR / "queries.npy")[:N_QUERIES]
    conn = await asyncpg.connect(DSN)
    try:
        # ウォームアップ(初回接続のプランキャッシュ・モジュールロード分を除外する)
        await conn.fetch(
            f"SELECT id FROM docs ORDER BY embedding <=> '{_vec_literal(queries[0])}' LIMIT 10"
        )

        plain_times = [await _plain_select(conn, _vec_literal(v)) for v in queries]
        set_local_times = [await _set_local_select(conn, _vec_literal(v)) for v in queries]
    finally:
        await conn.close()

    plain_stats = {
        "p50": _percentile(plain_times, 50),
        "p95": _percentile(plain_times, 95),
        "mean": round(statistics.mean(plain_times), 3),
    }
    set_local_stats = {
        "p50": _percentile(set_local_times, 50),
        "p95": _percentile(set_local_times, 95),
        "mean": round(statistics.mean(set_local_times), 3),
    }
    result: dict = {
        "n_queries": N_QUERIES,
        "plain_select_ms": plain_stats,
        "set_local_select_ms": set_local_stats,
        "overhead_p50_ms": round(set_local_stats["p50"] - plain_stats["p50"], 3),
        "overhead_p95_ms": round(set_local_stats["p95"] - plain_stats["p95"], 3),
    }
    print(result)
    return result


if __name__ == "__main__":
    asyncio.run(main())
