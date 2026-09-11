"""プールから checkout した接続で hnsw.ef_search が維持されているかを確かめるテスト。

`docker compose up -d` で DB が起動していることが前提。
"""

import pytest

from src.pool_factories import EF_SEARCH, make_pool_init_only, make_pool_init_setup

DB_QUERY = "SELECT id FROM docs ORDER BY embedding <=> '[" + ",".join(["0.01"] * 100) + "]' LIMIT 1"


async def test_init_setup_keeps_ef_search_across_acquires() -> None:
    """init= + setup= の実装は、2回目以降の acquire でも ef_search=200 を維持する。"""
    pool = await make_pool_init_setup(min_size=1, max_size=1)
    try:
        for _ in range(3):
            async with pool.acquire() as conn:
                await conn.fetchval(DB_QUERY)  # 拡張モジュールをロードさせる
                value = await conn.fetchval("SHOW hnsw.ef_search")
                assert value == str(EF_SEARCH)
    finally:
        await pool.close()


@pytest.mark.xfail(
    reason=(
        "init= だけの実装は asyncpg の RESET ALL で2回目以降の acquire から "
        "ef_search が消える既知の欠陥。setup= の追加が必要 (Issue #3 参照)"
    ),
    strict=True,
)
async def test_init_only_does_not_keep_ef_search_across_acquires() -> None:
    """init= だけの実装は、2回目の acquire で ef_search=200 が失われる(意図的に落ちるテスト)。"""
    pool = await make_pool_init_only(min_size=1, max_size=1)
    try:
        async with pool.acquire() as conn:
            await conn.fetchval(DB_QUERY)  # 1回目は init= の SET がまだ生きている

        async with pool.acquire() as conn:
            await conn.fetchval(DB_QUERY)
            value = await conn.fetchval("SHOW hnsw.ef_search")
            assert value == str(EF_SEARCH)  # ここで落ちる(実際には pgvector のデフォルト '40')
    finally:
        await pool.close()
