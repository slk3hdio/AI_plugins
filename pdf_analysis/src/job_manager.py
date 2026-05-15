from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from parser import create_parse_config, create_converter, parse_pdf

logger = logging.getLogger("pdf_analysis.jobs")

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
IDLE_CONVERTER_TIMEOUT_SECONDS = 600.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ParseJob:
    job_id: str
    input_path: str
    output_dir: str
    timeout_seconds: float
    status: JobStatus
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: list[dict[str, Any]] | None = None
    cancelled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QueueItem:
    job_id: str


@dataclass
class PipelineState:
    queue_max_size: int = 16
    artifacts_path: Path | None = None
    jobs: dict[str, ParseJob] = field(default_factory=dict)
    queue: asyncio.Queue[QueueItem] = field(init=False)
    worker_task: asyncio.Task[None] | None = None
    running_job_id: str | None = None
    converter: Any = None
    converter_ready: bool = False
    last_job_finished_at: str | None = None

    def __post_init__(self) -> None:
        self.queue = asyncio.Queue(maxsize=self.queue_max_size)


class JobManager:
    def __init__(self, queue_max_size: int = 16, artifacts_path: Path | None = None) -> None:
        self._state = PipelineState(queue_max_size=queue_max_size, artifacts_path=artifacts_path)
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._state.worker_task is not None:
                return
            self._state.worker_task = asyncio.create_task(self._worker_loop(), name="pdf-analysis-worker")
            logger.info("Started PDF analysis worker with queue_max_size=%s", self._state.queue_max_size)

    async def stop(self) -> None:
        async with self._lock:
            worker_task = self._state.worker_task
            self._state.worker_task = None
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        self._release_converter()

    def submit_job(
        self,
        input_path: str,
        output_dir: str | None,
        timeout_seconds: float = 500.0,
    ) -> dict[str, Any]:
        input_path_obj = Path(input_path).expanduser().resolve()
        if not input_path_obj.exists():
            raise ValueError(f"Input path does not exist: {input_path_obj}")

        if self._state.queue.full():
            raise RuntimeError("Job queue is full")

        job_id = uuid4().hex
        output_dir_obj = self._resolve_output_dir(job_id, output_dir)
        job = ParseJob(
            job_id=job_id,
            input_path=str(input_path_obj),
            output_dir=str(output_dir_obj),
            timeout_seconds=timeout_seconds,
            status="queued",
            submitted_at=_utc_now(),
        )
        self._state.jobs[job_id] = job
        self._state.queue.put_nowait(QueueItem(job_id=job_id))
        logger.info("Queued parse job %s for %s", job_id, input_path_obj)
        return {
            "job_id": job_id,
            "status": job.status,
            "queue_position": self._queue_position(job_id),
            "output_dir": job.output_dir,
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._require_job(job_id).to_dict()

    def list_jobs(self, status: JobStatus | None = None, limit: int = 100) -> dict[str, Any]:
        jobs = list(self._state.jobs.values())
        if status is not None:
            jobs = [job for job in jobs if job.status == status]
        jobs.sort(key=lambda job: job.submitted_at, reverse=True)
        return {
            "jobs": [job.to_dict() for job in jobs[:limit]],
            "count": min(len(jobs), limit),
        }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self._require_job(job_id)
        if job.status == "queued":
            job.cancelled = True
            job.status = "cancelled"
            job.finished_at = _utc_now()
            logger.info("Cancelled queued job %s", job_id)
            return {"job_id": job_id, "status": job.status}
        if job.status == "running":
            return {
                "job_id": job_id,
                "status": job.status,
                "message": "Running jobs cannot be cancelled safely",
            }
        return {"job_id": job_id, "status": job.status}

    def get_server_status(self) -> dict[str, Any]:
        return {
            "pipeline_count": 1,
            "worker_started": self._state.worker_task is not None,
            "running_job_id": self._state.running_job_id,
            "queued_jobs": self._state.queue.qsize(),
            "total_jobs": len(self._state.jobs),
            "queue_max_size": self._state.queue_max_size,
            "converter_ready": self._state.converter_ready,
            "idle_converter_timeout_seconds": IDLE_CONVERTER_TIMEOUT_SECONDS,
            "last_job_finished_at": self._state.last_job_finished_at,
        }

    def _create_converter(self):
        config = create_parse_config(
            input_path=Path(__file__),
            output_dir=Path(__file__).parent / "_unused",
            artifacts_path=self._state.artifacts_path,
            timeout_seconds=500.0,
        )
        return create_converter(config)

    async def _worker_loop(self) -> None:
        while True:
            try:
                item = await asyncio.wait_for(
                    self._state.queue.get(),
                    timeout=IDLE_CONVERTER_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                if self._state.converter is not None:
                    logger.info(
                        "No jobs received for %s seconds; releasing idle PDF converter",
                        IDLE_CONVERTER_TIMEOUT_SECONDS,
                    )
                    self._release_converter()
                continue
            try:
                job = self._state.jobs.get(item.job_id)
                if job is None or job.cancelled:
                    continue
                await self._run_job(job)
            finally:
                self._state.queue.task_done()

    async def _run_job(self, job: ParseJob) -> None:
        if self._state.converter is None:
            logger.info("Initializing PDF converter for first queued job")
            self._state.converter = await asyncio.to_thread(self._create_converter)
            self._state.converter_ready = True

        self._state.running_job_id = job.job_id
        job.status = "running"
        job.started_at = _utc_now()
        logger.info("Starting parse job %s", job.job_id)
        try:
            result = await asyncio.to_thread(self._parse_job, job)
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = _utc_now()
            self._state.last_job_finished_at = job.finished_at
            logger.exception("Parse job %s failed", job.job_id)
        else:
            job.status = "succeeded"
            job.result = result
            job.finished_at = _utc_now()
            self._state.last_job_finished_at = job.finished_at
            logger.info("Completed parse job %s", job.job_id)
        finally:
            self._state.running_job_id = None

    def _parse_job(self, job: ParseJob) -> list[dict[str, Any]]:
        config = create_parse_config(
            input_path=Path(job.input_path),
            output_dir=Path(job.output_dir),
            artifacts_path=self._state.artifacts_path,
            timeout_seconds=job.timeout_seconds,
        )
        return parse_pdf(config, converter=self._state.converter)

    def _resolve_output_dir(self, job_id: str, output_dir: str | None) -> Path:
        if output_dir:
            return Path(output_dir).expanduser().resolve()
        return (Path(__file__).parent / "jobs" / job_id / "output").resolve()

    def _release_converter(self) -> None:
        self._state.converter = None
        self._state.converter_ready = False

    def _require_job(self, job_id: str) -> ParseJob:
        job = self._state.jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job_id: {job_id}")
        return job

    def _queue_position(self, job_id: str) -> int:
        position = 0
        for item in list(self._state.queue._queue):
            if item.job_id == job_id:
                return position
            position += 1
        return -1


@asynccontextmanager
async def managed_job_manager(job_manager: JobManager):
    await job_manager.start()
    try:
        yield job_manager
    finally:
        await job_manager.stop()
