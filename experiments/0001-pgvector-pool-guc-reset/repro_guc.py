# /// script
# requires-python = ">=3.12"
# dependencies = ["asyncpg"]
# ///
"""asyncpg のコネクションプールで init= に渡した SET が RESET ALL で消えるかを確かめる最小再現。"""

import asyncio

import asyncpg

DSN = "postgresql://postgres:postgres@localhost:5433/postgres"


async def set_guc(conn: asyncpg.Connection) -> None:
    await conn.execute("SET hnsw.ef_search = 200")


async def probe(label: str, **kwargs: object) -> None:
    try:
        pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1, **kwargs)
    except Exception as e:
        print(f"{label:>18}: create_pool FAILED: {type(e).__name__}: {e}")
        return
    vals = []
    for _ in range(3):
        async with pool.acquire() as c:
            vals.append(await c.fetchval("SHOW hnsw.ef_search"))
    await pool.close()
    print(f"{label:>18}: acquire 1/2/3 = {vals}")


async def main() -> None:
    await probe("init only", init=set_guc)
    await probe("init+setup", init=set_guc, setup=set_guc)
    await probe("server_settings", server_settings={"hnsw.ef_search": "200"})


if __name__ == "__main__":
    asyncio.run(main())
