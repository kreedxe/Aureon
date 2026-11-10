import { getBackendConfig } from "@/lib/tauri";
import type {
  LanguageChoice,
  AIAction,
  AIJob,
  AIModelStatus,
  Product,
  ProductAvailability,
  ProductDescriptionDraft,
  ProductInput,
  ProductList,
  ProductSort,
  Recording,
  RecordingList,
  TranscriptionJob,
} from "@/lib/types";

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  json?: unknown;
  form?: FormData;
  timeout?: number;
}

async function request<T>(
  path: string,
  { method = "GET", json, form, timeout = 15_000 }: RequestOptions = {},
): Promise<T> {
  const config = await getBackendConfig();
  const headers: Record<string, string> = { "X-Session-Token": config.token };
  let body: BodyInit | undefined;
  if (form) {
    body = form;
  } else if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  let response: Response;
  try {
    response = await fetch(new URL(path, config.baseUrl), {
      method,
      headers,
      body,
      signal: AbortSignal.timeout(timeout),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("The local request timed out. Try again.");
    }
    throw new Error("Could not reach the local Python service. Check that Aureon is running.");
  }

  if (!response.ok) {
    let detail = `The local service returned an error (${response.status}).`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Keep the HTTP status message if the server response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function listRecordings(): Promise<RecordingList> {
  return request<RecordingList>("/api/v1/recordings");
}

export async function uploadRecording(
  blob: Blob,
  name: string,
  duration: number,
): Promise<Omit<Recording, "audioUrl">> {
  const form = new FormData();
  form.append("name", name);
  form.append("duration", String(duration));
  form.append("audio", blob, `recording.${extensionFor(blob.type)}`);
  return request("/api/v1/recordings", {
    method: "POST",
    form,
    timeout: 120_000,
  });
}

export async function renameRecording(
  recordingId: string,
  name: string,
): Promise<Omit<Recording, "audioUrl">> {
  return request(`/api/v1/recordings/${recordingId}`, {
    method: "PATCH",
    json: { name },
  });
}

export function deleteRecording(recordingId: string): Promise<void> {
  return request(`/api/v1/recordings/${recordingId}`, { method: "DELETE" });
}

export async function beginTranscription(
  recordingId: string,
  language: LanguageChoice,
): Promise<{ job_id: string }> {
  return request(`/api/v1/recordings/${recordingId}/transcriptions`, {
    method: "POST",
    json: { language: language === "auto" ? null : language },
  });
}

export function getTranscriptionJob(jobId: string): Promise<TranscriptionJob> {
  return request(`/api/v1/transcriptions/${jobId}`);
}

export function getAIModelStatus(): Promise<AIModelStatus> {
  return request("/api/v1/ai/status");
}

export function beginAIJob(
  recordingId: string,
  operation: AIAction,
  targetLanguage: Exclude<LanguageChoice, "auto"> | null,
): Promise<AIJob> {
  return request(`/api/v1/recordings/${recordingId}/ai`, {
    method: "POST",
    json: { operation, target_language: targetLanguage },
  });
}

export function getAIJob(jobId: string): Promise<AIJob> {
  return request(`/api/v1/ai/jobs/${jobId}`);
}

export async function listProducts(options: {
  query?: string;
  category?: string;
  availability?: ProductAvailability | "";
  sort?: ProductSort;
  descending?: boolean;
} = {}): Promise<ProductList> {
  const search = new URLSearchParams();
  if (options.query) search.set("query", options.query);
  if (options.category) search.set("category", options.category);
  if (options.availability) search.set("availability", options.availability);
  if (options.sort) search.set("sort", options.sort);
  if (options.descending) search.set("descending", "true");
  return request(`/api/v1/products${search.size ? `?${search.toString()}` : ""}`);
}

export function createProduct(product: ProductInput): Promise<Product> {
  return request("/api/v1/products", { method: "POST", json: product });
}

export function updateProduct(productId: string, product: ProductInput): Promise<Product> {
  return request(`/api/v1/products/${productId}`, { method: "PUT", json: product });
}

export function deleteProduct(productId: string): Promise<void> {
  return request(`/api/v1/products/${productId}`, { method: "DELETE" });
}

export function generateProductDescription(
  input: Pick<
    ProductInput,
    "name" | "price" | "currency" | "category" | "brand" | "specifications"
  >,
): Promise<ProductDescriptionDraft> {
  return request("/api/v1/products/description-draft", {
    method: "POST",
    json: input,
    timeout: 600_000,
  });
}

function extensionFor(mediaType: string): string {
  if (mediaType.includes("ogg")) return "ogg";
  if (mediaType.includes("mp4")) return "m4a";
  if (mediaType.includes("wav")) return "wav";
  if (mediaType.includes("flac")) return "flac";
  if (mediaType.includes("mpeg")) return "mp3";
  return "webm";
}
