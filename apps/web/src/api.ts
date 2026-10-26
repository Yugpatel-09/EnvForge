export interface Agent {
  id: string;
  name: string;
  adapter: "reference_solver" | "http_endpoint";
  config: { endpoint_url?: string };
}
export interface Environment {
  id: string;
  name: string;
  version: string;
  description: string;
  supported_suites: string[];
  supported_tiers: string[];
  tools: string[];
  limitations: string[];
  execution: string;
}
export interface Evaluation {
  id: string;
  name: string;
  environment_id: string;
  agent_id: string;
  status: string;
  suite: string;
  tier: string;
  completed_episodes: number;
  total_episodes: number;
  success_count: number;
  hard_failures_count: number;
  created_at: number;
  error: string | null;
  manifest: Record<string, unknown>;
}
export interface Episode {
  id: string;
  task_id: string;
  seed: number;
  status: string;
  success: boolean;
  reward: number;
}
export interface Step {
  action_id: string;
  tool: string;
  arguments: Record<string, unknown>;
  output: string;
  step: number;
  timestamp: number;
  state_diff: Record<string, unknown>;
}
export interface Trajectory {
  episode_id: string;
  action_history: Step[];
  initial_observation: { prompt: string };
  final_state: Record<string, unknown>;
  state_digest: string;
  duration_seconds: number;
}
export interface Verification {
  success: boolean;
  reward: number;
  reason: string;
  checks: Record<string, boolean>;
  hard_failures: string[];
  metadata: Record<string, unknown>;
  verifier_version: string;
}
export interface Report {
  metrics: {
    total_episodes: number;
    completed_episodes: number;
    success_rate: number | null;
    success_rate_95_ci: number[] | null;
    mean_reward: number | null;
    failure_clusters: Record<string, number>;
    release_gate_status: string;
  };
  provenance: Record<string, unknown>;
}
export interface QA {
  status: string;
  instances_tested?: number;
  reference_successes?: number;
  determinism_repeats?: number;
  determinism_passed?: boolean;
  manifest_digest?: string;
  exploit_checks?: Record<string, boolean>;
  limitations?: string[];
}

const base = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const token = sessionStorage.getItem("envforge-token");
  const response = await fetch(`${base}${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(15000),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`,
    );
  return data as T;
}

export function downloadJson(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
