/**
 * OpenClaw tools for the Drive Playground service (list, read, write).
 * Requires the Python drive_playground_service to be running and baseUrl/apiKey in plugin config.
 */

import { Type } from "@sinclair/typebox";
import type { OpenClawPluginApi } from "../../../src/plugins/types.js";
import type { AnyAgentTool } from "../../../src/agents/tools/common.js";
import { jsonResult } from "../../../src/agents/tools/common.js";

type PluginCfg = {
  baseUrl?: string;
  apiKey?: string;
};

function getConfig(api: OpenClawPluginApi): { baseUrl: string; apiKey: string } {
  const cfg = (api.pluginConfig ?? {}) as PluginCfg;
  const baseUrl = (cfg.baseUrl ?? process.env.DRIVE_PLAYGROUND_BASE_URL ?? "").trim();
  const apiKey =
    (cfg.apiKey ?? process.env.DRIVE_PLAYGROUND_API_KEY ?? "").trim();
  if (!baseUrl) {
    throw new Error("Drive Playground: baseUrl is required. Set it in plugin config or DRIVE_PLAYGROUND_BASE_URL.");
  }
  if (!apiKey) {
    throw new Error("Drive Playground: apiKey is required. Set it in plugin config or DRIVE_PLAYGROUND_API_KEY.");
  }
  return { baseUrl: baseUrl.replace(/\/$/, ""), apiKey };
}

async function fetchDrive(
  baseUrl: string,
  apiKey: string,
  path: string,
  options: { method?: string; body?: string } = {},
): Promise<{ ok: boolean; status: number; body: string }> {
  const url = `${baseUrl}${path}`;
  const res = await fetch(url, {
    method: options.method ?? "GET",
    headers: {
      "X-API-Key": apiKey,
      "Accept": "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
    },
    body: options.body,
  });
  const body = await res.text();
  return { ok: res.ok, status: res.status, body };
}

export function createDrivePlaygroundTools(api: OpenClawPluginApi): AnyAgentTool[] {
  const listSchema = Type.Object({
    folder_id: Type.Optional(
      Type.String({
        description:
          "Folder ID to list inside. Omit to list the Playground root. Use the id of a subfolder from a previous list to see files inside that subfolder.",
      }),
    ),
    page_token: Type.Optional(Type.String({ description: "Pagination token from previous list response." })),
    page_size: Type.Optional(Type.Number({ description: "Max files to return (1–100).", minimum: 1, maximum: 100 })),
  });
  const readSchema = Type.Object({
    file_id: Type.String({
      description: "Google Drive file ID from drive_playground_list. Can be a file in the root or inside any subfolder.",
    }),
  });
  const writeSchema = Type.Object({
    name: Type.String({
      description: "File name (e.g. notes.txt, report.docx, My Doc). Required.",
    }),
    content: Type.Optional(
      Type.String({
        description:
          "Full text content. Use for: (1) Plain text/markdown files (mime_type text/plain). (2) Google Doc: initial document text. (3) Google Sheet: CSV or tab-separated rows (e.g. 'col1,col2\\nval1,val2'). (4) Google Slides: first line = slide title, rest = body text. Exactly one of content, file_url, or neither (empty Google app) is required.",
      }),
    ),
    file_url: Type.Optional(
      Type.String({
        description:
          "HTTP or signed URL to a binary file (e.g. MP3, Office, PDF). Service downloads and uploads to Drive. Exactly one of content, file_url, or neither (empty Google app) is required.",
      }),
    ),
    mime_type: Type.Optional(
      Type.String({
        description:
          "MIME type. Default text/plain. Examples: text/plain, text/markdown, audio/mpeg, application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.google-apps.document, application/vnd.google-apps.spreadsheet, application/vnd.google-apps.presentation.",
      }),
    ),
    folder_id: Type.Optional(
      Type.String({
        description:
          "Folder ID to write into. Omit to write in the Playground root. Use a subfolder id from drive_playground_list to write inside that folder.",
      }),
    ),
  });

  return [
    {
      label: "Drive Playground (list)",
      name: "drive_playground_list",
      description:
        "List files in the OpenClaw Playground folder on Google Drive (My Drive → Personal → AI Research → OpenClaw Playground). Omit folder_id to list the root; pass a subfolder's id to list inside that subfolder. Returns id, name, mimeType, modifiedTime, size. Use to discover file IDs before reading.",
      parameters: listSchema,
      execute: async (_id, params) => {
        const { baseUrl, apiKey } = getConfig(api);
        const folderId = typeof params.folder_id === "string" ? params.folder_id.trim() : undefined;
        const pageToken = typeof params.page_token === "string" ? params.page_token : undefined;
        const pageSize = typeof params.page_size === "number" ? params.page_size : 50;
        const qs = new URLSearchParams();
        if (folderId) qs.set("folder_id", folderId);
        if (pageToken) qs.set("page_token", pageToken);
        qs.set("page_size", String(pageSize));
        const { ok, status, body } = await fetchDrive(baseUrl, apiKey, `/list?${qs.toString()}`);
        if (!ok) {
          throw new Error(`Drive Playground list failed: ${status} ${body}`);
        }
        return jsonResult(JSON.parse(body));
      },
    },
    {
      label: "Drive Playground (read)",
      name: "drive_playground_read",
      description:
        "Read the text content of a file in the OpenClaw Playground folder (root or any subfolder). Use drive_playground_list to get file IDs.",
      parameters: readSchema,
      execute: async (_id, params) => {
        const { baseUrl, apiKey } = getConfig(api);
        const fileId = typeof params.file_id === "string" ? params.file_id.trim() : "";
        if (!fileId) {
          throw new Error("file_id is required");
        }
        const { ok, status, body } = await fetchDrive(baseUrl, apiKey, `/files/${encodeURIComponent(fileId)}/content`);
        if (!ok) {
          throw new Error(`Drive Playground read failed: ${status} ${body}`);
        }
        return jsonResult({ content: body });
      },
    },
    {
      label: "Drive Playground (write)",
      name: "drive_playground_write",
      description:
        "Create or update a file in the OpenClaw Playground folder. (1) Text file: supply content and optional mime_type (default text/plain). (2) Google Doc with text: mime_type application/vnd.google-apps.document and content = initial document text. (3) Google Sheet with data: mime_type application/vnd.google-apps.spreadsheet and content = CSV or tab-separated rows. (4) Google Slides with text: mime_type application/vnd.google-apps.presentation and content = first line as slide title, remaining lines as body. (5) Empty Google Doc/Sheet/Slide: supply only name and that mime_type; no content. (6) Binary: file_url + mime_type (if service supports it). Exactly one of content, file_url, or neither (empty Google app) is required. Omit folder_id for Playground root.",
      parameters: writeSchema,
      execute: async (_id, params) => {
        const { baseUrl, apiKey } = getConfig(api);
        const name = typeof params.name === "string" ? params.name.trim() : "";
        const content = typeof params.content === "string" ? params.content : undefined;
        const file_url = typeof params.file_url === "string" ? params.file_url.trim() || undefined : undefined;
        const mime_type = typeof params.mime_type === "string" ? params.mime_type : "text/plain";
        const folder_id = typeof params.folder_id === "string" ? params.folder_id.trim() || undefined : undefined;
        if (!name) {
          throw new Error("name is required");
        }
        const hasContent = content !== undefined && content !== "";
        const hasFileUrl = file_url !== undefined && file_url !== "";
        const emptyGoogleApp =
          !hasContent &&
          !hasFileUrl &&
          /^application\/vnd\.google-apps\.(document|spreadsheet|presentation)$/.test(mime_type);
        if (!hasContent && !hasFileUrl && !emptyGoogleApp) {
          throw new Error(
            "Exactly one of content, file_url, or neither (empty Google Doc/Sheet/Slide with mime_type application/vnd.google-apps.document|spreadsheet|presentation) is required.",
          );
        }
        if ([hasContent, hasFileUrl, emptyGoogleApp].filter(Boolean).length > 1) {
          throw new Error("Supply only one of content, file_url, or neither (empty Google app).");
        }
        const bodyPayload: Record<string, unknown> = { name, mime_type };
        if (hasContent) bodyPayload.content = content;
        if (hasFileUrl) bodyPayload.file_url = file_url;
        if (folder_id !== undefined) bodyPayload.folder_id = folder_id;
        const { ok, status, body } = await fetchDrive(baseUrl, apiKey, "/write", {
          method: "POST",
          body: JSON.stringify(bodyPayload),
        });
        if (!ok) {
          throw new Error(`Drive Playground write failed: ${status} ${body}`);
        }
        return jsonResult(JSON.parse(body));
      },
    },
  ];
}
