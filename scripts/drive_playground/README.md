# Google Drive OpenClaw Playground service

Small HTTP API so your OpenClaw bot can list, read, and write files in a single Google Drive folder:

**My Drive → Personal → AI Research → OpenClaw Playground**

## 1. Google Cloud setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project (or pick one) and enable these APIs (APIs & Services → Enable APIs):
   - **Google Drive API**
   - **Google Docs API** (for creating Docs with initial text)
   - **Google Sheets API** (for creating Sheets with cell data)
   - **Google Slides API** (for creating Slides with title/body text)
3. **OAuth consent screen**: Configure if needed (External, add your email as test user).
4. **Credentials** → Create credentials → **OAuth client ID** → Application type: **Desktop app** → Create.
5. Download the JSON and save it as `credentials.json` in this directory (`scripts/drive_playground/`).

## 2. Folder in Drive

Create this structure in Google Drive (or use an existing one):

- **My Drive** → **Personal** → **AI Research** → **OpenClaw Playground**

Alternatively, open the folder you want in Drive, copy the folder ID from the URL  
(`https://drive.google.com/drive/folders/<FOLDER_ID>`) and set:

```bash
export DRIVE_PLAYGROUND_FOLDER_ID="your-folder-id"
```

Then the path above is ignored.

## 3. API key for OpenClaw

Choose a secret (e.g. a long random string) and set it so only your bot can call this API:

```bash
export DRIVE_PLAYGROUND_API_KEY="your-secret-api-key"
```

Use the same value in your OpenClaw plugin config when calling this service.

## 4. Run the service

```bash
cd scripts/drive_playground
pip install -r requirements.txt
python drive_playground_service.py
```

First run will open a browser for Google sign-in; the token is saved to `token.json` (do not commit it).

Default port: **8765**. Override with `PORT=9000 python drive_playground_service.py`.

To expose it to OpenClaw running elsewhere (e.g. Railway), run this on your PC and use **Tailscale** or **ngrok** so the gateway can reach the service, or run the service on a small VPS and point OpenClaw at that URL.

## 5. OpenClaw extension

This repo includes the **Drive Playground** extension at `extensions/drive-playground`. It registers three tools: `drive_playground_list`, `drive_playground_read`, `drive_playground_write`.

1. Enable the plugin in config (e.g. via `openclaw configure` or dashboard).
2. Set plugin config:
   - **baseUrl**: URL where this service is running (e.g. `http://localhost:8765` or your ngrok/VPS URL).
   - **apiKey**: Same value as `DRIVE_PLAYGROUND_API_KEY`.
3. Allow the tools for your agent (e.g. in `agents.defaults.tools.allow` add `drive_playground_list`, `drive_playground_read`, `drive_playground_write`, or allow the plugin group if your config supports it).
4. Restart the gateway after config changes.

## 6. API endpoints

All requests require header: `X-API-Key: <DRIVE_PLAYGROUND_API_KEY>` or `Authorization: Bearer <DRIVE_PLAYGROUND_API_KEY>`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | No auth; returns `{"status":"ok"}`. |
| GET | `/list` | List files in the Playground folder. Query: `page_token`, `page_size` (default 50). |
| GET | `/files/{file_id}/content` | Read file content (direct children of Playground only). |
| POST | `/write` | Create or update a file. Body: `name`, `mime_type`, and optionally `content`, `file_url`, `folder_id`. For **Google Doc**: `mime_type`: `application/vnd.google-apps.document` and `content`: initial text. For **Google Sheet**: `application/vnd.google-apps.spreadsheet` and `content`: CSV or tab-separated rows. For **Google Slides**: `application/vnd.google-apps.presentation` and `content`: first line = title, rest = body. For plain text: `content` and `mime_type` (default `text/plain`). |
