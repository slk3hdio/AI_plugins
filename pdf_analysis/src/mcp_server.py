from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi_mcp import FastApiMCP
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from job_manager import JobManager

logger = logging.getLogger("pdf_analysis.server")

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class SubmitParseRequest(BaseModel):
    input_path: str = Field(description="Path to a PDF file or directory containing PDF files")
    output_dir: str | None = Field(default=None, description="Optional output directory for parsed files")
    timeout_seconds: float = Field(default=500.0, ge=1.0, description="Per-document timeout in seconds")


def submit_parse_job(job_manager: JobManager, request: SubmitParseRequest) -> dict:
    try:
        return job_manager.submit_job(
            input_path=request.input_path,
            output_dir=request.output_dir,
            timeout_seconds=request.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


def get_parse_job(job_manager: JobManager, job_id: str) -> dict:
    try:
        return job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def list_parse_jobs(job_manager: JobManager, status: JobStatus | None = None, limit: int = 100) -> dict:
    return job_manager.list_jobs(status=status, limit=limit)


def cancel_parse_job(job_manager: JobManager, job_id: str) -> dict:
    try:
        return job_manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def get_server_status(job_manager: JobManager) -> dict:
    return job_manager.get_server_status()


def create_http_app(job_manager: JobManager) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await job_manager.start()
        try:
            yield
        finally:
            await job_manager.stop()

    app = FastAPI(
        title="PDF Analysis MCP Server",
        description="Queues PDF analysis jobs onto a single shared parsing pipeline.",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, **job_manager.get_server_status()}

    @app.post(
        "/api/jobs",
        operation_id="submit_pdf_parse",
        summary="Submit a PDF analysis job",
    )
    def submit_job(request: SubmitParseRequest) -> dict:
        return submit_parse_job(job_manager, request)

    @app.get(
        "/api/jobs/{job_id}",
        operation_id="get_parse_job",
        summary="Get a PDF analysis job by id",
    )
    def get_job(job_id: str) -> dict:
        return get_parse_job(job_manager, job_id)

    @app.get(
        "/api/jobs",
        operation_id="list_parse_jobs",
        summary="List PDF analysis jobs",
    )
    def list_jobs(
        status: Annotated[JobStatus | None, Query(description="Optional job status filter")] = None,
        limit: Annotated[int, Query(ge=1, le=1000, description="Maximum number of jobs to return")] = 100,
    ) -> dict:
        return list_parse_jobs(job_manager, status=status, limit=limit)

    @app.post(
        "/api/jobs/{job_id}/cancel",
        operation_id="cancel_parse_job",
        summary="Cancel a queued PDF analysis job",
    )
    def cancel_job(job_id: str) -> dict:
        return cancel_parse_job(job_manager, job_id)

    @app.get(
        "/api/server-status",
        operation_id="get_server_status",
        summary="Get PDF analysis server status",
    )
    def server_status() -> dict:
        return get_server_status(job_manager)

    mcp = FastApiMCP(
        app,
        include_operations=[
            "submit_pdf_parse",
            "get_parse_job",
            "list_parse_jobs",
            "cancel_parse_job",
            "get_server_status",
        ],
    )
    mcp.mount_http()
    return app


def create_stdio_server(job_manager: JobManager) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_: FastMCP):
        await job_manager.start()
        try:
            yield
        finally:
            await job_manager.stop()

    server = FastMCP(
        name="pdf-analysis",
        instructions="Queue PDF parsing requests onto a single shared pipeline and return job IDs for later polling.",
        lifespan=lifespan,
    )

    @server.tool(name="submit_pdf_parse", description="Submit a PDF analysis job and return its job id.")
    def submit_pdf_parse(
        input_path: str,
        output_dir: str | None = None,
        timeout_seconds: float = 500.0,
    ) -> dict:
        request = SubmitParseRequest(
            input_path=input_path,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
        )
        try:
            return job_manager.submit_job(
                input_path=request.input_path,
                output_dir=request.output_dir,
                timeout_seconds=request.timeout_seconds,
            )
        except (ValueError, RuntimeError) as exc:
            return {"error": str(exc)}

    @server.tool(name="get_parse_job", description="Get the current status or result of a PDF analysis job.")
    def stdio_get_parse_job(job_id: str) -> dict:
        try:
            return job_manager.get_job(job_id)
        except KeyError as exc:
            return {"error": str(exc)}

    @server.tool(name="list_parse_jobs", description="List known PDF analysis jobs.")
    def stdio_list_parse_jobs(status: JobStatus | None = None, limit: int = 100) -> dict:
        return job_manager.list_jobs(status=status, limit=limit)

    @server.tool(name="cancel_parse_job", description="Cancel a queued PDF analysis job.")
    def stdio_cancel_parse_job(job_id: str) -> dict:
        try:
            return job_manager.cancel_job(job_id)
        except KeyError as exc:
            return {"error": str(exc)}

    @server.tool(name="get_server_status", description="Get single-pipeline queue status.")
    def stdio_get_server_status() -> dict:
        return job_manager.get_server_status()

    return server
