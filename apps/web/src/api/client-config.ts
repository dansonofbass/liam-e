import { env } from "../env";
import type { CreateClientConfig } from "./generated/client.gen";

// Called by the generated hey-api client on init (via `runtimeConfigPath` in
// apps/web/openapi-ts.config.ts). Generated paths already include /api, so the
// base URL defaults to same-origin and only needs overriding for remote development.
export const apiBaseUrl = (): string => env.VITE_API_URL.replace(/\/+$/u, "");

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: apiBaseUrl(),
});
