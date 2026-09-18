"""asyncpg のプール生成を戦略ごとに切り出したモジュール。

`hnsw.ef_search` をプール全体に効かせるための5つの戦略を、同じ形の関数として提供する。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import asyncpg

DSN = "postgresql://postgres:postgres@localhost:5433/postgres"
EF_SEARCH = 200


async def _set_ef_search(conn: asyncpg.Connection, value: int = EF_SEARCH) -> None:
    # SET はパラメータ化できないため、int() でキャストしてから埋め込む
    await conn.execute(f"SET hnsw.ef_search = {int(value)}")


async def make_pool_init_only(dsn: str = DSN, **kw: object) -> asyncpg.Pool:
    """戦略①: init= だけで接続ごとに1回だけ SET する。"""
    return await asyncpg.create_pool(dsn, init=_set_ef_search, **kw)  # type: ignore[arg-type]


async def make_pool_init_setup(dsn: str = DSN, **kw: object) -> asyncpg.Pool:
    """戦略②: init= に加えて setup= でも SET し、acquire のたびに再適用する。"""
    return await asyncpg.create_pool(
        dsn,
        init=_set_ef_search,
        setup=_set_ef_search,
        **kw,  # type: ignore[arg-type]
    )


async def make_pool_server_settings(dsn: str = DSN, **kw: object) -> asyncpg.Pool:
    """戦略③: server_settings= で起動パケットのランタイムパラメータとして渡す。"""
    return await asyncpg.create_pool(
        dsn,
        server_settings={"hnsw.ef_search": str(EF_SEARCH)},
        **kw,  # type: ignore[arg-type]
    )


async def make_pool_pgoptions(dsn: str = DSN, **kw: object) -> asyncpg.Pool:
    """戦略⑤: PGOPTIONS 相当（起動パケットの options フィールドに -c で渡す）。"""
    return await asyncpg.create_pool(
        dsn,
        server_settings={"options": f"-c hnsw.ef_search={EF_SEARCH}"},  # type: ignore[arg-type]
        **kw,
    )


PoolFactory = Callable[..., Awaitable[asyncpg.Pool]]

# 戦略④(SET LOCAL)はプール生成ではなくクエリ単位の関数なので、ここでは公開しない。
POOL_STRATEGIES: dict[str, PoolFactory] = {
    "init only": make_pool_init_only,
    "init+setup": make_pool_init_setup,
    "server_settings": make_pool_server_settings,
    "pgoptions": make_pool_pgoptions,
}


async def query_with_set_local(
    conn: asyncpg.Connection, sql: str, *args: object, ef_search: int = EF_SEARCH
) -> list[asyncpg.Record]:
    """戦略④: トランザクションで囲み、SET LOCAL でクエリ単位にだけ効かせる。"""
    async with conn.transaction():
        await conn.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
        return await conn.fetch(sql, *args)
