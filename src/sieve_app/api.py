"""Expose ranking and screening through one FastAPI listener."""

from contextlib import AsyncExitStack, asynccontextmanager

from candidate_screening.api import app as screening_app
from fastapi import FastAPI

from talent_ranker.api import app as ranking_app


def create_app(ranking: FastAPI = ranking_app, screening: FastAPI = screening_app) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(ranking.router.lifespan_context(ranking))
            await stack.enter_async_context(screening.router.lifespan_context(screening))
            yield

    app = FastAPI(title="Sieve API", lifespan=lifespan)
    app.mount("/api/ranking", ranking)
    app.mount("/api", screening)
    return app


app = create_app()
