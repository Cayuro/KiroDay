// Thin typed HTTP client around fetch. It centralizes base URL resolution,
// JSON encoding, and decoding of the backend error envelope
// `{ "error": { "code", "message", "details" } }` into a typed ApiError.

import type { ApiErrorEnvelope } from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";

/** Resolve the backend base URL from Vite env, trimming any trailing slash. */
export function getBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL;
  const base = fromEnv && fromEnv.trim().length > 0 ? fromEnv : DEFAULT_BASE_URL;
  return base.replace(/\/+$/, "");
}

/** Typed error carrying the backend's machine-readable code and details. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details?: unknown;

  constructor(code: string, message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function isErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  return (
    typeof value === "object" &&
    value !== null &&
    "error" in value &&
    typeof (value as ApiErrorEnvelope).error === "object"
  );
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  /** Query parameters; undefined values are skipped. */
  query?: Record<string, string | number | undefined>;
}

/** Perform a JSON request and decode the response or throw a typed ApiError. */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query } = options;

  const url = new URL(`${getBaseUrl()}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (networkError) {
    // Network / CORS / server-down failures never reach the server envelope.
    throw new ApiError(
      "NETWORK_ERROR",
      "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.",
      0,
      networkError,
    );
  }

  // 204 or empty body: return undefined cast to T (callers type accordingly).
  const text = await response.text();
  const payload: unknown = text.length > 0 ? JSON.parse(text) : undefined;

  if (!response.ok) {
    if (isErrorEnvelope(payload)) {
      const { code, message, details } = payload.error;
      throw new ApiError(code, message, response.status, details);
    }
    throw new ApiError(
      "UNKNOWN_ERROR",
      "Ocurrió un error inesperado en el servidor.",
      response.status,
      payload,
    );
  }

  return payload as T;
}
