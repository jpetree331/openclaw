#!/usr/bin/env python3
"""
Google Drive "OpenClaw Playground" service for OpenClaw.

Scopes access to a single folder:
  My Drive --> Personal --> AI Research --> OpenClaw Playground

Exposes a small HTTP API (list, read, write) so an OpenClaw tool can call it.
Supports creating Google Docs, Sheets, and Slides with initial text/content.
Run: uvicorn drive_playground_service:app --host 0.0.0.0 --port 8765

Setup:
  1. Create a project in Google Cloud Console; enable Google Drive API,
     Google Docs API, Google Sheets API, and Google Slides API.
  2. Create OAuth 2.0 credentials (Desktop app), download as credentials.json
     into this directory (or set GOOGLE_APPLICATION_CREDENTIALS).
  3. Set DRIVE_PLAYGROUND_API_KEY (secret for OpenClaw to call this API).
  4. Set DRIVE_PLAYGROUND_FOLDER_ID to your folder ID (from Drive URL when you
     open the folder), OR leave unset to resolve by path:
     Personal / AI Research / OpenClaw Playground
  5. First run: a browser will open for Google sign-in; token is saved to
     token.json (add to .gitignore).
"""

import csv
import json
import os
import io
from pathlib import Path

# Load .env from this directory so DRIVE_PLAYGROUND_* and GOOGLE_* can be set in a file (do not commit .env).
SCRIPT_DIR = Path(__file__).resolve().parent
_dotenv_path = SCRIPT_DIR / ".env"
if _dotenv_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_dotenv_path)
    except ImportError:
        pass

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

# Google Drive, Docs, Sheets, Slides
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/presentations",
]
CREDENTIALS_FILE = SCRIPT_DIR / "credentials.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"
# Folder path to resolve if DRIVE_PLAYGROUND_FOLDER_ID is not set (under My Drive root)
PLAYGROUND_PATH = ["Personal", "AI Research", "OpenClaw Playground"]


def get_api_key() -> str:
    key = (os.environ.get("DRIVE_PLAYGROUND_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set DRIVE_PLAYGROUND_API_KEY in the environment.")
    return key


def _get_creds() -> Credentials:
    """Load credentials from env (Railway) or from token/credentials files (local)."""
    creds = None
    token_json = (os.environ.get("GOOGLE_DRIVE_TOKEN_JSON") or "").strip()
    if token_json:
        try:
            token_data = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(
                "GOOGLE_DRIVE_TOKEN_JSON is set but invalid. Paste the full contents of token.json (from a local OAuth run)."
            ) from e
    elif TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        # First-time OAuth (local only; use credentials file or env)
        creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or CREDENTIALS_FILE
        credentials_json = (os.environ.get("GOOGLE_DRIVE_CREDENTIALS_JSON") or "").strip()
        if credentials_json:
            try:
                client_config = json.loads(credentials_json)
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                creds = flow.run_local_server(port=0)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(
                    "GOOGLE_DRIVE_CREDENTIALS_JSON is set but invalid. Paste the full contents of credentials.json."
                ) from e
        elif creds_path and Path(creds_path).exists():
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise FileNotFoundError(
                "Google OAuth credentials not found. For Railway: set GOOGLE_DRIVE_TOKEN_JSON (full token.json from a local OAuth run). "
                "For local first run: save credentials.json here or set GOOGLE_DRIVE_CREDENTIALS_JSON."
            )
        if not token_json and TOKEN_FILE.exists() is False:
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
    return creds


def get_drive_service():
    return build("drive", "v3", credentials=_get_creds())


def get_docs_service():
    return build("docs", "v1", credentials=_get_creds())


def get_sheets_service():
    return build("sheets", "v4", credentials=_get_creds())


def get_slides_service():
    return build("slides", "v1", credentials=_get_creds())


def get_playground_folder_id(service) -> str:
    folder_id = (os.environ.get("DRIVE_PLAYGROUND_FOLDER_ID") or "").strip()
    if folder_id:
        return folder_id
    # Resolve by path: My Drive -> Personal -> AI Research -> OpenClaw Playground
    parent_id = "root"
    for name in PLAYGROUND_PATH:
        result = (
            service.files()
            .list(
                q=f"'{parent_id}' in parents and name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                spaces="drive",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
        files = result.get("files", [])
        if not files:
            raise ValueError(
                f"Folder not found: {' / '.join(PLAYGROUND_PATH)}. "
                f"Missing after: {name}. Create the folder in Drive or set DRIVE_PLAYGROUND_FOLDER_ID to the folder ID."
            )
        parent_id = files[0]["id"]
    return parent_id


def _is_under_root(service, file_or_folder_id: str, root_id: str, seen: set | None = None) -> bool:
    """Return True if file_or_folder_id is the root or a descendant of root_id (no cycles)."""
    seen = seen or set()
    if file_or_folder_id in seen:
        return False
    seen.add(file_or_folder_id)
    if file_or_folder_id == root_id:
        return True
    try:
        meta = service.files().get(fileId=file_or_folder_id, fields="parents").execute()
    except Exception:
        return False
    parents = meta.get("parents") or []
    return any(_is_under_root(service, p, root_id, seen) for p in parents)


def require_api_key(x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    key = get_api_key()
    bearer = (authorization or "").strip().removeprefix("Bearer ")
    if (x_api_key or bearer) != key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# -----------------------------------------------------------------------------
# FastAPI app
# -----------------------------------------------------------------------------
app = FastAPI(
    title="Drive Playground API",
    description="List, read, and write files in OpenClaw Playground folder on Google Drive.",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/list", dependencies=[])
def list_files(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    folder_id: str | None = Query(None),
    page_token: str | None = Query(None),
    page_size: int = Query(50, ge=1, le=100),
):
    require_api_key(x_api_key, authorization)
    service = get_drive_service()
    root_id = get_playground_folder_id(service)
    list_folder_id = (folder_id or "").strip() or root_id
    if list_folder_id != root_id and not _is_under_root(service, list_folder_id, root_id):
        raise HTTPException(
            status_code=403,
            detail="folder_id must be the Playground root or a subfolder under it.",
        )
    q = f"'{list_folder_id}' in parents and trashed = false"
    result = (
        service.files()
        .list(
            q=q,
            spaces="drive",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            pageSize=page_size,
            pageToken=page_token or "",
        )
        .execute()
    )
    return {
        "files": result.get("files", []),
        "nextPageToken": result.get("nextPageToken"),
    }


@app.get("/files/{file_id}/content")
def read_file(
    file_id: str,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    require_api_key(x_api_key, authorization)
    service = get_drive_service()
    root_id = get_playground_folder_id(service)
    meta = service.files().get(fileId=file_id, fields="id, name, mimeType, parents").execute()
    if not _is_under_root(service, file_id, root_id):
        raise HTTPException(
            status_code=403,
            detail="File is not in the Playground folder or its subfolders. Use /list to get file IDs.",
        )
    try:
        request = service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return PlainTextResponse(buf.read().decode("utf-8", errors="replace"))
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


# Google app MIME types
MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_GOOGLE_SLIDES = "application/vnd.google-apps.presentation"


def _doc_insert_text(doc_id: str, text: str, at_index: int = 1) -> None:
    """Insert text into a Google Doc at the given index (1 = start of body)."""
    docs = get_docs_service()
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": at_index}, "text": text}}]},
    ).execute()


def _sheet_set_values(sheet_id: str, rows: list[list[str]]) -> None:
    """Set cell values in the first sheet. rows is a list of rows (each row a list of cell values)."""
    if not rows:
        return
    sheets = get_sheets_service()
    sheets.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def _slides_ensure_first_slide_and_insert_text(
    presentation_id: str, title: str, body: str
) -> None:
    """Ensure the presentation has at least one slide (TITLE_AND_BODY), then insert title and body text."""
    slides_svc = get_slides_service()
    pres = slides_svc.presentations().get(presentationId=presentation_id).execute()
    pres_slides = pres.get("slides", [])

    if not pres_slides:
        # New presentation is empty; add a TITLE_AND_BODY slide first
        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={
                "requests": [
                    {
                        "createSlide": {
                            "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                            "placeholderIdMappings": [],
                        }
                    }
                ]
            },
        ).execute()
        pres = slides_svc.presentations().get(presentationId=presentation_id).execute()
        pres_slides = pres.get("slides", [])

    if not pres_slides:
        return
    slide = pres_slides[0]
    elements = slide.get("pageElements", [])
    requests = []
    for el in elements:
        obj_id = el.get("objectId")
        placeholder = (el.get("shape") or {}).get("placeholder")
        if not obj_id or not placeholder:
            continue
        ptype = placeholder.get("type")
        if ptype == "TITLE" and title:
            requests.append({"insertText": {"objectId": obj_id, "text": title, "insertionIndex": 1}})
        elif ptype in ("BODY", "SUBTITLE") and body:
            requests.append({"insertText": {"objectId": obj_id, "text": body, "insertionIndex": 1}})
    if requests:
        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={"requests": requests},
        ).execute()


class WriteBody(BaseModel):
    name: str
    content: str | None = None
    mime_type: str = "text/plain"
    file_url: str | None = None
    folder_id: str | None = None


def _parse_sheet_content(content: str) -> list[list[str]]:
    """Parse content as CSV (comma or tab separated) into rows of cell values."""
    lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]
    if not lines:
        return []
    # Use tab if first line has more tabs than commas; else comma
    delim = "\t" if lines[0].count("\t") >= lines[0].count(",") else ","
    reader = csv.reader(io.StringIO(content), delimiter=delim)
    return [[str(c).strip() for c in row] for row in reader if row]


@app.post("/write")
def write_file(
    body: WriteBody,
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
):
    require_api_key(x_api_key, authorization)
    drive = get_drive_service()
    root_id = get_playground_folder_id(drive)
    folder_id = (body.folder_id or "").strip() or root_id
    if folder_id != root_id and not _is_under_root(drive, folder_id, root_id):
        raise HTTPException(
            status_code=403,
            detail="folder_id must be the Playground root or a subfolder under it.",
        )
    existing = (
        drive.files()
        .list(
            q=f"'{folder_id}' in parents and name = '{body.name}' and trashed = false",
            fields="files(id)",
            pageSize=1,
        )
        .execute()
    )
    files = existing.get("files", [])
    file_id = files[0]["id"] if files else None
    mime = (body.mime_type or "text/plain").strip()

    # --- Google Doc with content ---
    if mime == MIME_GOOGLE_DOC and (body.content or "").strip():
        if file_id:
            doc = get_docs_service().documents().get(documentId=file_id).execute()
            end_index = doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 2)
            _doc_insert_text(file_id, "\n" + (body.content or "").strip(), at_index=end_index - 1)
            return {"id": file_id, "action": "updated"}
        meta = {"name": body.name, "mimeType": mime, "parents": [folder_id]}
        created = drive.files().create(body=meta, fields="id").execute()
        doc_id = created["id"]
        _doc_insert_text(doc_id, (body.content or "").strip())
        return {"id": doc_id, "action": "created"}

    # --- Google Sheet with content (CSV) ---
    if mime == MIME_GOOGLE_SHEET and (body.content or "").strip():
        if file_id:
            _sheet_set_values(file_id, _parse_sheet_content(body.content or ""))
            return {"id": file_id, "action": "updated"}
        meta = {"name": body.name, "mimeType": mime, "parents": [folder_id]}
        created = drive.files().create(body=meta, fields="id").execute()
        sheet_id = created["id"]
        _sheet_set_values(sheet_id, _parse_sheet_content(body.content or ""))
        return {"id": sheet_id, "action": "created"}

    # --- Google Slides with content (first line = title, rest = body) ---
    if mime == MIME_GOOGLE_SLIDES and (body.content or "").strip():
        if file_id:
            lines = (body.content or "").strip().split("\n", 1)
            title = lines[0] if lines else ""
            body_text = lines[1] if len(lines) > 1 else ""
            _slides_ensure_first_slide_and_insert_text(file_id, title, body_text)
            return {"id": file_id, "action": "updated"}
        meta = {"name": body.name, "mimeType": mime, "parents": [folder_id]}
        created = drive.files().create(body=meta, fields="id").execute()
        pres_id = created["id"]
        lines = (body.content or "").strip().split("\n", 1)
        title = lines[0] if lines else ""
        body_text = lines[1] if len(lines) > 1 else ""
        _slides_ensure_first_slide_and_insert_text(pres_id, title, body_text)
        return {"id": pres_id, "action": "created"}

    # --- Empty Google Doc/Sheet/Slides (no content) ---
    if mime in (MIME_GOOGLE_DOC, MIME_GOOGLE_SHEET, MIME_GOOGLE_SLIDES):
        if file_id:
            return {"id": file_id, "action": "unchanged"}
        meta = {"name": body.name, "mimeType": mime, "parents": [folder_id]}
        created = drive.files().create(body=meta, fields="id").execute()
        return {"id": created["id"], "action": "created"}

    # --- Binary from URL (placeholder: service would fetch and upload) ---
    if body.file_url:
        raise HTTPException(
            status_code=501,
            detail="file_url upload not implemented in this service; use content for text or Google app types.",
        )

    # --- Plain text / blob file ---
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required for non-Google-app mime types")
    meta = {"name": body.name, "mimeType": mime, "parents": [folder_id]}
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime,
        resumable=False,
    )
    if file_id:
        drive.files().update(fileId=file_id, body={"name": body.name}).execute()
        drive.files().update(fileId=file_id, media_body=media).execute()
        return {"id": file_id, "action": "updated"}
    created = drive.files().create(body=meta, media_body=media, fields="id").execute()
    return {"id": created["id"], "action": "created"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="0.0.0.0", port=port)
