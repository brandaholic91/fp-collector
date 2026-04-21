from fastapi import Request
import asyncpg


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool
