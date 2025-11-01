# -*- coding: utf-8 -*-
import os
from typing import List, Optional
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.parser import decode_tags, process_questions, build_grouped_questions
from app.db import make_engine, init_db, insert_doc, get_doc

PORT = int(os.getenv("PORT", "8080"))
STORAGE_DIR = os.getenv("STORAGE_DIR", "storage")

app = FastAPI(title="FDB Viewer")
templates = Jinja2Templates(directory="app/templates")

os.makedirs(STORAGE_DIR, exist_ok=True)
# Раздача ассетов: /s/<doc_id>/assets/<file>
app.mount("/s", StaticFiles(directory=STORAGE_DIR), name="storage")

engine = make_engine()
init_db(engine)

ALLOWED_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

def await_read(file: UploadFile) -> bytes:
    file.file.seek(0)
    return file.file.read()

def _unique_target(path: str) -> str:
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    i = 1
    while True:
        cand = f"{root}-{i}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1

def _save_assets_flat(doc_id: str, files: List[UploadFile]):
    """
    Сохраняет изображения ПЛОСКО в storage/<doc_id>/assets/<basename>.
    Директории из исходного имени игнорируются. Конфликты имен -> -1, -2, ...
    """
    base = os.path.join(STORAGE_DIR, doc_id, "assets")
    os.makedirs(base, exist_ok=True)
    for f in files or []:
        name = f.filename or ""
        if not name:
            continue
        basename = os.path.basename(name)
        if not basename:
            continue
        ext = os.path.splitext(basename)[1].lower()
        if ext not in ALLOWED_IMG_EXT:
            continue
        target = os.path.join(base, basename)
        target = _unique_target(target)
        with open(target, "wb") as out:
            out.write(await_read(f))

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload(
    fdb: UploadFile = File(...),                   # обязателен
    dirs: Optional[List[UploadFile]] = File(None)  # файлы из выбранных папок (webkitdirectory multiple)
):
    """
    Принимает .fdb и (опционально) набор папок с картинками.
    Картинки сохраняются плоско по basename в /assets.
    """
    # читаем fdb
    raw_bytes = await_read(fdb)
    try:
        content = raw_bytes.decode("cp1251", errors="ignore")
    except Exception:
        content = raw_bytes.decode("utf-8", errors="ignore")

    decoded_tags, _gr = decode_tags(content)
    xml_data = "\n".join(decoded_tags)
    questions = process_questions(xml_data)
    grouped_questions = build_grouped_questions(questions)

    # создаём документ
    doc_id = insert_doc(engine, grouped_questions, title=(fdb.filename or None))

    # сохраняем ассеты ПЛОСКО (только из папок)
    if dirs:
        _save_assets_flat(doc_id, dirs)

    return RedirectResponse(url=f"/{doc_id}", status_code=303)

@app.get("/{doc_id}", response_class=HTMLResponse)
async def view(request: Request, doc_id: str):
    doc = get_doc(engine, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    asset_base = f"/s/{doc_id}/assets/"
    return templates.TemplateResponse("viewer.html", {
        "request": request,
        "doc_id": doc_id,
        "title": doc.get("title") or f"Документ {doc_id}",
        "data_json": doc["json"],
        "asset_base": asset_base,
    })

@app.get("/api/doc/{doc_id}.json")
async def api_doc(doc_id: str):
    doc = get_doc(engine, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден")
    return doc["json"]

@app.get("/healthz")
async def healthz():
    return {"ok": True}
