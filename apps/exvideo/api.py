"""ex-video 백엔드 라우터 (/api/exvideo/…).

원본 ex-video 의 `web/server.py` 를 통합 셸의 APIRouter 로 옮긴 것.
작업 결과는 `data/exvideo/jobs/<job_id>/` 아래에 쌓인다.

`/notes/…` 는 전사 + 강의자료 PDF 를 묶어 요약정리본 PDF 를 만드는 쪽으로,
`data/exvideo/notes/<source_id>/` 아래에 쌓인다.
"""
from __future__ import annotations

import io
import os
import re
import threading
import uuid
import zipfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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


# ───────────────────────────── 요약정리본 (/notes) ─────────────────────────────
#
# 흐름:  업로드 → (1회) 인덱스 생성 → 인덱스만 입력으로 정리본 PDF 여러 번 생성
#
# 원본 전사와 강의자료 PDF 는 서버에 남지만, 정리본을 만들 때 통째로 다시
# 보내지 않는다. 그래서 두 번째 요청부터 입력 토큰이 크게 떨어진다.

NOTE_JOBS: dict[str, dict] = {}
_note_lock = threading.Lock()


def _note_job(fn) -> str:
    """진행상황을 폴링할 수 있는 백그라운드 작업 하나를 띄운다."""
    job_id = uuid.uuid4().hex[:12]
    with _note_lock:
        NOTE_JOBS[job_id] = {"status": "queued", "progress": 0, "messages": [],
                             "result": None, "error": None}

    def progress(msg, pct=None):
        with _note_lock:
            job = NOTE_JOBS[job_id]
            job["messages"].append(msg)
            job["status"] = "running"
            if pct is not None:
                job["progress"] = pct

    def run():
        try:
            result = fn(progress)
            with _note_lock:
                NOTE_JOBS[job_id].update(status="done", progress=100, result=result)
        except Exception as exc:  # noqa: BLE001 - 원인을 그대로 보여 준다
            with _note_lock:
                NOTE_JOBS[job_id].update(status="error", error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=run, daemon=True).start()
    return job_id


@router.get("/notes/jobs/{job_id}")
def note_job_status(job_id: str) -> dict:
    with _note_lock:
        job = NOTE_JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@router.get("/notes/parts")
def note_parts() -> list[dict]:
    """정리본에서 고를 수 있는 구성 조각 목록."""
    from .exvideo.notes.render import PARTS

    return [{"id": k, "name": n, "desc": d} for k, (n, d) in PARTS.items()]


@router.post("/notes/sources")
async def create_source(
    title: str = Form(""),
    job_id: str = Form(""),
    transcript: str = Form(""),
    pdf: UploadFile | None = File(None),
) -> dict:
    """강의자료 PDF + 전사를 하나의 소스로 등록한다.

    전사는 셋 중 하나로 받는다: 직접 붙여넣기(transcript),
    앞서 돌린 추출 작업 이어받기(job_id), 아니면 생략(PDF 만).
    """
    from .exvideo.notes import index as notes_index

    text = transcript
    if job_id and not text:
        tpath = os.path.join(JOBS_DIR, job_id, "transcript.txt")
        if not os.path.exists(tpath):
            raise HTTPException(404, f"작업 {job_id} 의 전사본이 없습니다")
        with open(tpath, encoding="utf-8") as f:
            text = f.read()

    pdf_bytes = await pdf.read() if pdf is not None else None
    if pdf_bytes is not None and not pdf_bytes:
        pdf_bytes = None

    try:
        source_id = notes_index.create_source(
            title, pdf_bytes=pdf_bytes,
            pdf_name=(pdf.filename if pdf else ""), transcript_text=text,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return notes_index.load_meta(source_id)


@router.get("/notes/sources")
def list_sources() -> list[dict]:
    from .exvideo.notes import index as notes_index

    return notes_index.list_sources()


@router.get("/notes/sources/{source_id}")
def get_source(source_id: str) -> dict:
    from .exvideo.notes import index as notes_index
    from .exvideo.notes import render as notes_render

    meta = notes_index.load_meta(source_id)
    if not meta:
        raise HTTPException(404, "source not found")
    return {
        "meta": meta,
        "index": notes_index.load_index(source_id),
        "outputs": notes_render.list_outputs(source_id),
        "usage": notes_index.read_usage(source_id),
    }


class IndexRequest(BaseModel):
    provider: str | None = None
    model: str | None = None


@router.post("/notes/sources/{source_id}/index")
def build_index(source_id: str, req: IndexRequest) -> dict:
    from .exvideo.notes import index as notes_index

    if not notes_index.load_meta(source_id):
        raise HTTPException(404, "source not found")
    return {"job_id": _note_job(lambda p: notes_index.build_index(
        source_id, provider_name=req.provider, model=req.model, progress=p))}


class RenderRequest(BaseModel):
    parts: list[str] = ["toc", "summary", "concepts"]
    sections: list[str] | None = None      # 인덱스에서 쓸 섹션 (없으면 전체)
    raw_sections: list[str] | None = None  # 이 섹션만 원문까지 다시 읽는다
    note: str = ""
    provider: str | None = None
    model: str | None = None


@router.post("/notes/sources/{source_id}/render")
def render_notes(source_id: str, req: RenderRequest) -> dict:
    from .exvideo.notes import index as notes_index
    from .exvideo.notes import render as notes_render

    if not notes_index.load_index(source_id):
        raise HTTPException(409, "인덱스가 아직 없습니다. 먼저 인덱스를 만드세요.")
    return {"job_id": _note_job(lambda p: notes_render.generate(
        source_id, parts=req.parts, section_ids=req.sections, note=req.note,
        raw_sections=req.raw_sections, provider_name=req.provider, model=req.model,
        progress=p))}


@router.get("/notes/sources/{source_id}/outputs/{render_id}.pdf")
def get_output_pdf(source_id: str, render_id: str) -> FileResponse:
    from .exvideo.notes import index as notes_index

    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", render_id):
        raise HTTPException(400, "잘못된 render_id")
    path = os.path.join(notes_index.source_dir(source_id, "outputs"), f"{render_id}.pdf")
    if not os.path.exists(path):
        raise HTTPException(404, "결과물이 없습니다")
    return FileResponse(path, media_type="application/pdf",
                        filename=f"정리본_{render_id}.pdf")
