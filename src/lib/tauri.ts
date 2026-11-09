import { invoke, isTauri } from "@tauri-apps/api/core";
import type { BackendConfig } from "@/lib/types";

export async function getBackendConfig(): Promise<BackendConfig> {
  if (!isTauri()) {
    throw new Error("The Python backend is available when the desktop application is running.");
  }
  return invoke<BackendConfig>("get_backend_config");
}
