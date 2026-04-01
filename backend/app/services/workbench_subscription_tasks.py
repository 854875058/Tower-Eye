from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.models import WorkbenchSubscription
from app.services.workbench import WorkbenchService
from app.services.workbench_tasks import get_workbench_task_manager

logger = get_logger(__name__)


class WorkbenchSubscriptionManager:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[int] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._poller: asyncio.Task | None = None
        self._queued: set[int] = set()
        self._active: set[int] = set()
        self._started = False

    async def startup(self) -> None:
        if self._started:
            return
        self._started = True
        self._workers = [asyncio.create_task(self._worker())]
        self._poller = asyncio.create_task(self._poll_due_subscriptions())
        logger.info("Workbench subscription manager started")

    async def shutdown(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._poller:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            try:
                await worker
            except asyncio.CancelledError:
                pass
        self._workers.clear()
        self._queued.clear()
        self._active.clear()

    async def enqueue_subscription(self, subscription_id: int) -> None:
        if subscription_id in self._queued or subscription_id in self._active:
            return
        self._queued.add(subscription_id)
        await self.queue.put(subscription_id)

    async def _poll_due_subscriptions(self) -> None:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    result = await db.execute(
                        select(WorkbenchSubscription.id)
                        .where(
                            WorkbenchSubscription.is_enabled.is_(True),
                            WorkbenchSubscription.next_run_at.is_not(None),
                            WorkbenchSubscription.next_run_at <= datetime.utcnow(),
                        )
                        .order_by(WorkbenchSubscription.next_run_at.asc(), WorkbenchSubscription.id.asc())
                    )
                    subscription_ids = [row[0] for row in result.all()]

                for subscription_id in subscription_ids:
                    await self.enqueue_subscription(subscription_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Polling workbench subscriptions failed: %s", exc, exc_info=True)

            await asyncio.sleep(30)

    async def _worker(self) -> None:
        while True:
            subscription_id = await self.queue.get()
            self._queued.discard(subscription_id)
            self._active.add(subscription_id)
            try:
                async with AsyncSessionLocal() as db:
                    service = WorkbenchService(db)
                    subscription, new_count = await service.run_subscription(subscription_id)
                    if new_count > 0:
                        await get_workbench_task_manager().enqueue_dataset(subscription.dataset_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Workbench subscription run failed: %s", exc, exc_info=True)
            finally:
                self._active.discard(subscription_id)
                self.queue.task_done()


workbench_subscription_manager = WorkbenchSubscriptionManager()


def get_workbench_subscription_manager() -> WorkbenchSubscriptionManager:
    return workbench_subscription_manager
