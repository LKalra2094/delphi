"""Thin async Postgres client over asyncpg with a shared connection pool.

Preserves the original three-write pattern interface (query/insert/upsert).
All persistence callers wrap these in try/except and never raise (see §10.5).
"""
import os

import asyncpg

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            os.environ["DATABASE_URL"], min_size=1, max_size=5
        )
    return _pool


class PostgresClient:
    async def query_rows(
        self,
        table: str,
        filters: list[dict] | None = None,
        columns: str = "*",
        limit: int | None = None,
        order_by: str | None = None,
    ) -> list[dict]:
        where, args = "", []
        if filters:
            clauses = []
            for i, f in enumerate(filters, 1):
                op = {"eq": "=", "gte": ">=", "lte": "<=", "like": "LIKE", "ilike": "ILIKE"}[
                    f["op"]
                ]
                clauses.append(f'"{f["column"]}" {op} ${i}')
                args.append(f["value"])
            where = "WHERE " + " AND ".join(clauses)
        order = f"ORDER BY {order_by}" if order_by else ""
        lim = f"LIMIT {int(limit)}" if limit else ""
        sql = f'SELECT {columns} FROM "{table}" {where} {order} {lim}'
        pool = await _get_pool()
        async with pool.acquire() as c:
            return [dict(r) for r in await c.fetch(sql, *args)]

    async def insert_rows(self, table: str, rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        pool = await _get_pool()
        n = 0
        async with pool.acquire() as c:
            for r in rows:
                ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
                await c.execute(
                    f'INSERT INTO "{table}" ({collist}) VALUES ({ph})',
                    *[r[k] for k in cols],
                )
                n += 1
        return n

    async def upsert_rows(
        self,
        table: str,
        rows: list[dict],
        conflict_columns: list[str],
        update_columns: list[str],
    ) -> int:
        if not rows:
            return 0
        cols = list(rows[0].keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        conflict = ", ".join(f'"{c}"' for c in conflict_columns)
        sets = ", ".join(f'"{c}"=EXCLUDED."{c}"' for c in update_columns)
        pool = await _get_pool()
        n = 0
        async with pool.acquire() as c:
            for r in rows:
                ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
                await c.execute(
                    f'INSERT INTO "{table}" ({collist}) VALUES ({ph}) '
                    f"ON CONFLICT ({conflict}) DO UPDATE SET {sets}",
                    *[r[k] for k in cols],
                )
                n += 1
        return n

    async def insert_ignore(
        self, table: str, rows: list[dict], conflict_columns: list[str]
    ) -> int:
        """INSERT ... ON CONFLICT DO NOTHING. Used by the idempotent seeder."""
        if not rows:
            return 0
        cols = list(rows[0].keys())
        collist = ", ".join(f'"{c}"' for c in cols)
        conflict = ", ".join(f'"{c}"' for c in conflict_columns)
        pool = await _get_pool()
        n = 0
        async with pool.acquire() as c:
            for r in rows:
                ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
                await c.execute(
                    f'INSERT INTO "{table}" ({collist}) VALUES ({ph}) '
                    f"ON CONFLICT ({conflict}) DO NOTHING",
                    *[r[k] for k in cols],
                )
                n += 1
        return n
