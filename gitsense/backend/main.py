from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from backend.database import engine, Base
from backend.routes import auth, repos, webhook, commits
from backend.config import settings
from pydantic import PydanticDeprecatedSince20
import warnings

warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)

# Import all models so SQLAlchemy registers them before create_all
from backend.models import user, repo, commit, report, notification  # noqa


import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, func
from backend.database import AsyncSessionLocal
from backend.models.commit import Commit

logger = logging.getLogger(__name__)

STALE_ANALYSIS_TIMEOUT_MINUTES = 15
RECOVERY_CHECK_INTERVAL_SECONDS = 300  # every 5 minutes


async def _recover_stale_analyses():
    """
    Catches commits orphaned by an actual process restart mid-analysis
    (Step 1's try/except cannot catch this — the process dies before
    any except block runs). Runs for the lifetime of the app.
    """
    while True:
        await asyncio.sleep(RECOVERY_CHECK_INTERVAL_SECONDS)
        try:
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=STALE_ANALYSIS_TIMEOUT_MINUTES)
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    update(Commit)
                    .where(
                        Commit.status.in_(["analyzing", "pending", "retrying"]),
                        func.coalesce(Commit.updated_at, Commit.created_at) < cutoff,
                    )
                    .values(
                        status="failed",
                        status_detail="Recovered: analysis stalled past timeout — "
                                       "likely orphaned by a server restart. Use the "
                                       "Retry button to re-run analysis.",
                    )
                )
                await db.commit()
                if result.rowcount > 0:
                    logger.warning(f"[recovery] Marked {result.rowcount} stale commit(s) as failed")
        except Exception as e:
            # This loop must never die, or recovery silently stops for
            # the rest of the app's lifetime — always catch and continue
            logger.error(f"[recovery] Stale-analysis recovery check failed: {e}")


QUEUE_POLL_INTERVAL_SECONDS = 2


async def _analysis_queue_consumer():
    """
    Background loop that dequeues analysis tasks from Redis
    and executes them under semaphore-controlled concurrency.

    HIGH priority queue is always drained before LOW.
    Max concurrent analyses = MAX_CONCURRENT_ANALYSES (3).
    """
    from backend.services.analysis_queue import dequeue_task

    while True:
        try:
            task = await dequeue_task()
            if task is None:
                await asyncio.sleep(QUEUE_POLL_INTERVAL_SECONDS)
                continue

            # Spawn task execution asynchronously under semaphore control
            asyncio.create_task(_run_queued_task(task))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[queue-consumer] Loop error: {e}")
            await asyncio.sleep(QUEUE_POLL_INTERVAL_SECONDS)


async def _run_queued_task(task: dict):
    """Execute a single queued task under semaphore control."""
    from backend.services.analysis_queue import get_analysis_semaphore
    from backend.routes.webhook import _analyze_commit, _reanalyze_commit_bg
    from backend.models.repo import ConnectedRepo

    sem = get_analysis_semaphore()
    async with sem:
        repo_id = task.get("repo_id")
        commit_id = task.get("commit_id")
        task_type = task.get("type", "analyze")

        if task_type == "retry":
            await _reanalyze_commit_bg(repo_id, commit_id)
        else:
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Commit, ConnectedRepo)
                    .join(ConnectedRepo, ConnectedRepo.id == Commit.repo_id)
                    .where(Commit.id == commit_id, ConnectedRepo.id == repo_id)
                )
                row = result.first()
                if not row:
                    logger.error(f"[queue] Commit {commit_id}/repo {repo_id} not found")
                    return
                commit, repo = row
                try:
                    await _analyze_commit(db, repo, commit)
                except Exception as e:
                    logger.error(f"[queue] Analysis failed for commit {commit_id}: {e}",
                                 exc_info=True)
                    try:
                        await db.rollback()
                        commit.status = "failed"
                        commit.status_detail = f"Queue analysis failed: {type(e).__name__}: {str(e)[:200]}"
                        await db.commit()
                    except Exception as db_err:
                        logger.error(f"[queue] Could not record failure: {db_err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    recovery_task = asyncio.create_task(_recover_stale_analyses())
    queue_task = asyncio.create_task(_analysis_queue_consumer())
    yield
    recovery_task.cancel()
    queue_task.cancel()
    try:
        await asyncio.gather(recovery_task, queue_task, return_exceptions=True)
    except Exception:
        pass
    # Flush Langfuse traces before shutdown
    try:
        from langfuse import get_client
        lf = get_client()
        lf.flush()
        logger.info("Langfuse traces flushed on shutdown")
    except Exception:
        pass
    from backend.services.redis_client import close_redis_client
    await close_redis_client()
    await engine.dispose()



app = FastAPI(
    title="GitSense AI",
    description="Engineering Intelligence Platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:8501", "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(repos.router)
app.include_router(webhook.router)
app.include_router(commits.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "GitSense AI"}
