"""5戦略 × プール max_size ごとに、SHOW hnsw.ef_search が 200 でなかった割合を実測する。

各 (戦略, max_size) の組について N_REQUESTS 回 acquire → SHOW → release を繰り返す。
SET LOCAL 戦略はプールではなくクエリ単位の話なので、代わりに毎リクエスト
BEGIN; SET LOCAL; SHOW; COMMIT; を実行する形で計測する（常に 200 になるはず）。
"""

from __future__ import annotations

import asyncio

import asyncpg

from .pool_factories import DSN, EF_SEARCH, POOL_STRATEGIES

N_REQUESTS = 50
MAX_SIZES = [1, 5, 20]


_PROBE_VEC = "[" + ",".join("0.01" for _ in range(100)) + "]"


async def _one_request(pool: asyncpg.Pool) -> str:
    async with pool.acquire() as conn:
        # 本番同様、実際に vector 検索を1回走らせてから SHOW する
        # (これをしないと pgvector の拡張モジュールがそのセッションで未ロードのままになる)
        await conn.fetchval(f"SELECT id FROM docs ORDER BY embedding <=> '{_PROBE_VEC}' LIMIT 1")
        return await conn.fetchval("SHOW hnsw.ef_search")


async def measure_pool_strategy(name: str, factory, max_size: int) -> dict:
    pool = await factory(min_size=max_size, max_size=max_size)
    try:
        # max_size を超える同時リクエストを発生させ、プールが接続を使い回す状況を再現する
        # (逐次実行だと同じ接続が毎回再利用されるだけで max_size の効果が見えないため)
        values = await asyncio.gather(*(_one_request(pool) for _ in range(N_REQUESTS)))
    finally:
        await pool.close()
    ok = sum(1 for v in values if v == str(EF_SEARCH))
    return {
        "strategy": name,
        "max_size": max_size,
        "n_requests": N_REQUESTS,
        "ok": ok,
        "not_200_pct": round((N_REQUESTS - ok) / N_REQUESTS * 100, 1),
        "sample_values": values[:5],
    }


async def _one_set_local_request(pool: asyncpg.Pool) -> str:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {EF_SEARCH}")
        return await conn.fetchval("SHOW hnsw.ef_search")


async def measure_set_local(max_size: int) -> dict:
    pool = await asyncpg.create_pool(DSN, min_size=max_size, max_size=max_size)
    try:
        values = await asyncio.gather(*(_one_set_local_request(pool) for _ in range(N_REQUESTS)))
    finally:
        await pool.close()
    ok = sum(1 for v in values if v == str(EF_SEARCH))
    return {
        "strategy": "SET LOCAL (per-query)",
        "max_size": max_size,
        "n_requests": N_REQUESTS,
        "ok": ok,
        "not_200_pct": round((N_REQUESTS - ok) / N_REQUESTS * 100, 1),
        "sample_values": values[:5],
    }


async def main() -> list[dict]:
    results = []
    for max_size in MAX_SIZES:
        for name, factory in POOL_STRATEGIES.items():
            r = await measure_pool_strategy(name, factory, max_size)
            results.append(r)
            print(r)
        r = await measure_set_local(max_size)
        results.append(r)
        print(r)
    return results


if __name__ == "__main__":
    asyncio.run(main())
