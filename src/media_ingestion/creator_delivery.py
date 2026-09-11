import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .infrai_storage import InfraiError, InfraiStorage
from .upload_policy import plan_upload

BUCKET = os.environ.get("MEDIA_BUCKET", "creator-media")


class AssetIngestRequest(BaseModel):
    creator_id: str = Field(min_length=1, max_length=80)
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(pattern=r"^(video|audio)/")
    size_bytes: int = Field(gt=0)


class UploadPart(BaseModel):
    part_number: int
    upload_url: str


class AssetIngestResponse(BaseModel):
    asset_id: str
    object_key: str
    mode: Literal["single", "multipart"]
    part_size: int
    upload_id: str | None = None
    upload_url: str | None = None
    parts: list[UploadPart] = []


class CompletedPart(BaseModel):
    part_number: int = Field(gt=0)
    etag: str = Field(min_length=1)


class CompleteUploadRequest(BaseModel):
    upload_id: str = Field(min_length=1)
    parts: list[CompletedPart] = Field(min_length=1)


class ProcessingJob(BaseModel):
    job_id: str
    asset_id: str
    state: Literal["queued"]
    object_key: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    storage = InfraiStorage()
    try:
        await storage.create_bucket(BUCKET)
    except InfraiError as exc:
        # Startup is idempotent when the configured bucket already exists.
        if exc.status_code != 409:
            raise
    app.state.storage = storage
    app.state.assets = {}
    app.state.jobs = {}
    try:
        yield
    finally:
        await storage.close()


app = FastAPI(title="Creator media ingestion", lifespan=lifespan)


@app.exception_handler(InfraiError)
async def infrai_error_handler(_: Request, exc: InfraiError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code < 500 else 502
    return JSONResponse(status_code=status, content={"code": exc.code, "detail": exc.detail})


@app.post("/assets/ingest", response_model=AssetIngestResponse)
async def start_ingest(body: AssetIngestRequest, request: Request) -> AssetIngestResponse:
    asset_id = uuid4().hex
    safe_filename = body.filename.replace("/", "_")
    object_key = f"creators/{body.creator_id}/{asset_id}/{safe_filename}"
    plan = plan_upload(body.size_bytes)
    storage: InfraiStorage = request.app.state.storage

    if plan.mode == "single":
        signed = await storage.presign_object(
            BUCKET,
            object_key,
            op="put",
            content_type=body.content_type,
            max_bytes=body.size_bytes,
            idempotency_key=asset_id,
        )
        request.app.state.assets[asset_id] = object_key
        return AssetIngestResponse(
            asset_id=asset_id,
            object_key=object_key,
            mode="single",
            part_size=plan.part_size,
            upload_url=signed["url"],
        )

    created = await storage.create_multipart(
        BUCKET,
        object_key,
        body.content_type,
        asset_id,
    )
    upload_id = created["upload_id"]
    parts = [
        UploadPart(
            part_number=number,
            upload_url=(await storage.presign_part(upload_id, number))["url"],
        )
        for number in range(1, plan.part_count + 1)
    ]
    request.app.state.assets[asset_id] = object_key
    return AssetIngestResponse(
        asset_id=asset_id,
        object_key=object_key,
        mode="multipart",
        part_size=plan.part_size,
        upload_id=upload_id,
        parts=parts,
    )


@app.post("/assets/{asset_id}/complete", response_model=ProcessingJob)
async def complete_ingest(
    asset_id: str,
    body: CompleteUploadRequest,
    request: Request,
) -> ProcessingJob:
    object_key = request.app.state.assets.get(asset_id)
    if object_key is None:
        raise HTTPException(status_code=404, detail="Asset session not found")
    storage: InfraiStorage = request.app.state.storage
    await storage.complete_multipart(
        body.upload_id,
        [part.model_dump() for part in body.parts],
        f"complete-{asset_id}",
    )
    job = ProcessingJob(
        job_id=uuid4().hex,
        asset_id=asset_id,
        state="queued",
        object_key=object_key,
    )
    request.app.state.jobs[job.job_id] = job
    return job


@app.get("/jobs/{job_id}", response_model=ProcessingJob)
async def get_job(job_id: str, request: Request) -> ProcessingJob:
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Processing job not found")
    return job
