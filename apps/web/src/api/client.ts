import { z } from "zod";

import { accessToken, handleUnauthorized } from "./auth";

export class ApiError extends Error {
  readonly status: number;
  readonly url: string;
  readonly body: unknown;

  constructor(message: string, opts: { status: number; url: string; body?: unknown }) {
    super(message);
    this.name = "ApiError";
    this.status = opts.status;
    this.url = opts.url;
    this.body = opts.body;
  }
}

function apiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL?.trim();
  if (!value) throw new Error("Missing VITE_API_BASE_URL");
  return value.replace(/\/+$/, "");
}

function joinUrl(path: string): string {
  if (path.startsWith("http")) return path;
  if (!path.startsWith("/")) path = `/${path}`;
  return `${apiBaseUrl()}${path}`;
}

async function readErrorBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  try {
    if (contentType.includes("application/json")) return await response.json();
    return await response.text();
  } catch {
    return null;
  }
}

export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const url = joinUrl(input);
  const token = accessToken();

  const headers = new Headers(init?.headers);
  headers.set("accept", headers.get("accept") ?? "application/json");
  if (!headers.has("content-type") && init?.body && typeof init.body === "string") {
    headers.set("content-type", "application/json");
  }
  if (token) headers.set("authorization", `Bearer ${token}`);

  const response = await fetch(url, { ...init, headers });
  if (response.status === 401) {
    handleUnauthorized();
  }
  return response;
}

export async function apiFetchJson<T>(
  input: string,
  opts: { method?: string; body?: unknown; schema: z.ZodType<T, z.ZodTypeDef, unknown> }
): Promise<T> {
  const response = await apiFetch(input, {
    method: opts.method ?? "GET",
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body)
  });

  if (!response.ok) {
    const body = await readErrorBody(response);
    throw new ApiError(`API request failed (${response.status})`, {
      status: response.status,
      url: response.url,
      body
    });
  }

  const json = (await response.json()) as unknown;
  return opts.schema.parse(json);
}
