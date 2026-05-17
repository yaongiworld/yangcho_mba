"use client";

/**
 * Manual matcher-trigger button + toast feedback.
 *
 * The server action triggerMatching() fires the match-pending.yml workflow
 * via GitHub's REST API. The action returns {ok, error}; until v1 we just
 * had a form-submit-and-hope flow with zero user feedback. This component:
 *
 *   * Shows a loading state while the dispatch is in flight (~200ms-2s).
 *   * Surfaces success or failure in a transient toast at top-right.
 *   * Calls router.refresh() on success so the Pipeline Runs table re-reads
 *     (the new run typically lands in pipeline_runs ~10-30 sec later, but
 *     the refresh is cheap and the user gets the "it's working" signal).
 *
 * No toast library — one styled div, faded out by setTimeout. Light + no
 * deps.
 */

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { triggerMatching } from "./trigger";

type Toast = { kind: "success" | "error"; message: string } | null;

const TOAST_DURATION_MS = 4000;

export function TriggerButton() {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [toast, setToast] = useState<Toast>(null);

  function fire() {
    startTransition(async () => {
      const result = await triggerMatching();
      if (result.ok) {
        setToast({
          kind: "success",
          message:
            "Pipeline triggered. The new run will appear in 10–30 seconds.",
        });
        // Server has revalidated /admin; re-read on the client too.
        router.refresh();
      } else {
        setToast({
          kind: "error",
          message: result.error ?? "Trigger failed.",
        });
      }
      // Auto-dismiss.
      setTimeout(() => setToast(null), TOAST_DURATION_MS);
    });
  }

  return (
    <>
      <button
        type="button"
        onClick={fire}
        disabled={isPending}
        className="rounded bg-neutral-900 text-white text-xs font-medium px-3 py-1.5 hover:bg-neutral-700 transition-colors disabled:opacity-60 disabled:cursor-wait"
      >
        {isPending ? "Triggering…" : "Run matcher now ↻"}
      </button>

      {toast && (
        <div
          role="status"
          className={`fixed top-4 right-4 z-50 max-w-sm rounded-lg shadow-lg px-4 py-3 border text-sm leading-snug ${
            toast.kind === "success"
              ? "bg-emerald-50 border-emerald-300 text-emerald-900"
              : "bg-rose-50 border-rose-300 text-rose-900"
          }`}
        >
          {toast.message}
        </div>
      )}
    </>
  );
}
