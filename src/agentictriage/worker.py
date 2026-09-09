from __future__ import annotations

import asyncio

from agentictriage.config import Settings
from agentictriage.fallback import FallbackRouter
from agentictriage.jobs import PostgresJobQueue, run_worker
from agentictriage.pipeline import TriagePipeline
from agentictriage.storage import PostgresStateStore


async def main() -> None:
    settings = Settings.from_environment()
    if not settings.database_url:
        raise RuntimeError("TRIAGE_DATABASE_URL is required")
    store = PostgresStateStore(settings.database_url)
    await store.open()
    try:
        await run_worker(
            PostgresJobQueue(store.pool),
            TriagePipeline(FallbackRouter(settings.providers()), store),
        )
    finally:
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
