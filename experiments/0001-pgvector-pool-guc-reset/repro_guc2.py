# /// script
# requires-python = ">=3.12"
# dependencies = ["asyncpg"]
# ///
"""実際に HNSW 検索(vector型を触るクエリ)を挟んだ場合、RESET ALL 後に ef_search がどうなるかを確認する。"""

import asyncio

import asyncpg

DSN = "postgresql://postgres:postgres@localhost:5433/postgres"


async def set_guc(conn: asyncpg.Connection) -> None:
    await conn.execute("SET hnsw.ef_search = 200")


async def main() -> None:
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=1, init=set_guc)
    async with pool.acquire() as c:
        await c.execute("CREATE TEMP TABLE t (v vector(3))")
        await c.execute("INSERT INTO t VALUES ('[1,2,3]')")
        await c.execute("CREATE INDEX ON t USING hnsw (v vector_l2_ops)")
        await c.fetchval("SELECT v FROM t ORDER BY v <-> '[1,2,3]' LIMIT 1")
        print("1st acquire (vector query 実行後):", await c.fetchval("SHOW hnsw.ef_search"))
    # TEMP TABLE は接続が変わると見えなくなるので、2回目以降は SHOW だけ見る
    for i in range(2, 4):
        async with pool.acquire() as c:
            print(f"{i}回目 acquire:", await c.fetchval("SHOW hnsw.ef_search"))
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
