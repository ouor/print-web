import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin as admin_api
from app.api import jobs as jobs_api
from app.core.config import settings
from app.db.engine import init_db
from app.printer.worker import worker_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(worker_loop(stop_event), name="print-worker")
    try:
        yield
    finally:
        stop_event.set()
        try:
            await asyncio.wait_for(worker_task, timeout=10)
        except asyncio.TimeoutError:
            worker_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="print-web", version="0.1.0", lifespan=lifespan)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(jobs_api.router)
    app.include_router(admin_api.router)

    return app


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
