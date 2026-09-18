"""戦略ごとに recall@10 を実測する。

プールを「暖機後」の状態（max_size=5 の同時接続で使い回される状態）を想定し、
200件のクエリを流したときの recall@10 を戦略ごとに比較する。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
import numpy as np

from .pool_factories import DSN, EF_SEARCH, POOL_STRATEGIES, query_with_set_local

MAX_SIZE = 5
DATA_DIR = Path(__file__).resolve().parent.parent / ".data"


def _vec_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


async def _top10_pool(pool: asyncpg.Pool, vec: np.ndarray) -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT id FROM docs ORDER BY embedding <=> '{_vec_literal(vec)}' LIMIT 10"
        )
    return [r["id"] for r in rows]


async def _top10_set_local(pool: asyncpg.Pool, vec: np.ndarray) -> list[int]:
    async with pool.acquire() as conn:
        rows = await query_with_set_local(
            conn,
            f"SELECT id FROM docs ORDER BY embedding <=> '{_vec_literal(vec)}' LIMIT 10",
            ef_search=EF_SEARCH,
        )
    return [r["id"] for r in rows]


def recall_at_10(retrieved: list[int], truth: np.ndarray) -> float:
    truth_set = set(truth.tolist())
    return len(set(retrieved) & truth_set) / len(truth_set)


async def measure_strategy(
    name: str, top10_fn, queries: np.ndarray, ground_truth: np.ndarray
) -> dict:
    # max_size 分だけ同時に投げ、プールが暖機後に使い回される状況を再現する
    # (gather は渡した順序で結果を返すので、先頭 MAX_SIZE 件が「まだ200のまま」の接続に
    #  あたりやすいという再現性は保ちつつ、逐次実行より実運用のトラフィックに近い)
    retrieved_all = await asyncio.gather(*(top10_fn(i) for i in range(len(queries))))
    recalls = [recall_at_10(retrieved_all[i], ground_truth[i]) for i in range(len(queries))]
    return {
        "strategy": name,
        "n_queries": len(queries),
        "recall_at_10_mean": round(float(np.mean(recalls)), 4),
        "recall_at_10_first5_mean": round(float(np.mean(recalls[:5])), 4),
        "recall_at_10_after_first5_mean": round(float(np.mean(recalls[5:])), 4),
        "per_query_recall": [round(r, 4) for r in recalls],
    }


async def main() -> list[dict]:
    queries = np.load(DATA_DIR / "queries.npy")
    ground_truth = np.load(DATA_DIR / "ground_truth.npy")

    results = []
    for name, factory in POOL_STRATEGIES.items():
        pool = await factory(min_size=MAX_SIZE, max_size=MAX_SIZE)
        try:

            async def fn(i: int, pool: asyncpg.Pool = pool) -> list[int]:
                return await _top10_pool(pool, queries[i])

            r = await measure_strategy(name, fn, queries, ground_truth)
        finally:
            await pool.close()
        print({k: v for k, v in r.items() if k != "per_query_recall"})
        results.append(r)

    # SET LOCAL 戦略
    pool = await asyncpg.create_pool(DSN, min_size=MAX_SIZE, max_size=MAX_SIZE)
    try:

        async def fn_local(i: int, pool: asyncpg.Pool = pool) -> list[int]:
            return await _top10_set_local(pool, queries[i])

        r = await measure_strategy("SET LOCAL (per-query)", fn_local, queries, ground_truth)
    finally:
        await pool.close()
    print({k: v for k, v in r.items() if k != "per_query_recall"})
    results.append(r)

    return results


if __name__ == "__main__":
    asyncio.run(main())
