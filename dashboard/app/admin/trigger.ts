/**
 * Server Action for the /admin "Run matcher now" button.
 *
 * Fires the `match-pending.yml` GitHub Actions workflow via the workflow_dispatch
 * REST API. The dispatch returns 204 with no body; the run shows up within
 * 10–30 seconds at github.com/{owner}/{repo}/actions, and writes its output to
 * pipeline_runs (visible in /admin's pipeline-runs section) on completion.
 *
 * Architectural note: ALL LLM work lives in Python on GitHub Actions; the
 * dashboard never calls Anthropic directly. This keeps a single mental
 * model — "DB reads happen in the dashboard, all LLM work happens in the
 * Python pipeline" — and means we don't need to maintain the matcher in
 * two languages.
 *
 * Required env vars (dashboard/.env.local):
 *   GITHUB_TOKEN          PAT with `actions:write` scope on the repo.
 *                         Classic PAT needs `repo` + `workflow`; fine-grained
 *                         needs Actions:Write on this single repo.
 *   GITHUB_REPO_OWNER     e.g. "yaongiworld"
 *   GITHUB_REPO_NAME      e.g. "yangcho_mba"
 *   GITHUB_DEFAULT_BRANCH e.g. "main"
 */

"use server";

import { revalidatePath } from "next/cache";

const WORKFLOW_FILE = "match-pending.yml";

export interface TriggerResult {
  ok: boolean;
  error?: string;
}

export async function triggerMatching(): Promise<TriggerResult> {
  const token = process.env.GITHUB_TOKEN;
  const owner = process.env.GITHUB_REPO_OWNER;
  const repo = process.env.GITHUB_REPO_NAME;
  const ref = process.env.GITHUB_DEFAULT_BRANCH ?? "main";

  if (!token || !owner || !repo) {
    return {
      ok: false,
      error:
        "GitHub trigger not configured. Set GITHUB_TOKEN + GITHUB_REPO_OWNER + GITHUB_REPO_NAME in dashboard/.env.local.",
    };
  }

  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${WORKFLOW_FILE}/dispatches`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref }),
    });
  } catch (exc) {
    return {
      ok: false,
      error: `Network error contacting GitHub: ${exc instanceof Error ? exc.message : String(exc)}`,
    };
  }

  if (res.status !== 204) {
    let detail = "";
    try {
      const body = await res.text();
      detail = body ? ` — ${body.slice(0, 240)}` : "";
    } catch {
      // ignore
    }
    return { ok: false, error: `GitHub returned HTTP ${res.status}${detail}` };
  }

  // Dispatch accepted. The workflow run appears within seconds; its
  // pipeline_runs row writes when it finishes (~30–60s typical).
  revalidatePath("/admin");
  return { ok: true };
}
