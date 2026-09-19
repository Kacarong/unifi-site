"""ex-video 백엔드 라우터 (/api/exvideo/…).

원본 ex-video 의 `web/server.py` 를 통합 셸의 APIRouter 로 옮긴 것.
작업 결과는 `data/exvideo/jobs/<job_id>/` 아래에 쌓인다.
"""
from __future__ import annotations

import io
import os
import threading
import uuid
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from server.paths import data_dir

from .exvideo.pipeline import run_pipeline

JOBS_DIR = data_dir("exvideo", "jobs")

router = APIRouter()

JOBS: dict[str, dict] = {}
_lock = threading.Lock()


class JobRequest(BaseModel):
    source: str
    transcribe: bool = True
    ocr: bool = True
    figures: bool = True
    model: str = "large-v3"
    cpu: bool = False


def _worker(job_id: str, req: JobRequest) -> None:
    out_dir = os.path.join(JOBS_DIR, job_id)

    def progress(msg, pct=None):
        with _lock:
            job = JOBS[job_id]
            job["messages"].append(msg)
            if pct is not None:
                job["progress"] = pct
            job["status"] = "running"

    try:
        res = run_pipeline(
            req.source,
            out_dir,
            model=req.model,
            do_transcribe=req.transcribe,
            do_ocr=req.ocr,
            do_figures=req.figures,
            cpu=req.cpu,
            progress=progress,
        )
        with _lock:
            JOBS[job_id].update(status="done", progress=100, result=res)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 그대로 보여준다
        with _lock:
            JOBS[job_id].update(status="error", error=str(exc))


def _get_done_job(job_id: str) -> dict:
    with _lock:
        job = JOBS.get(job_id)
    if not job or job.get("status") != "done":
        raise HTTPException(404, "not ready")
    return job


@router.post("/jobs")
def create_job(req: JobRequest) -> dict:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        JOBS[job_id] = {
            "status": "queued",
            "progress": 0,
            "messages": [],
            "result": None,
            "error": None,
        }
    threading.Thread(target=_worker, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with _lock:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return dict(job)


@router.get("/jobs/{job_id}/bundle")
def get_bundle(job_id: str) -> FileResponse:
    job = _get_done_job(job_id)
    return FileResponse(job["result"]["bundle"], media_type="text/markdown", filename="bundle.md")


@router.get("/jobs/{job_id}/download")
def download_zip(job_id: str) -> StreamingResponse:
    _get_done_job(job_id)
    out_dir = os.path.join(JOBS_DIR, job_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(out_dir):
            for name in files:
                if name == "source_video.mp4":
                    continue  # 원본 영상은 제외
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, out_dir))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="exvideo_{job_id}.zip"'},
    )
