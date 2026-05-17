/**
 * /admin/login — username + password form.
 *
 * Posts to the signin Server Action in this folder. On success, the action
 * sets the session cookie and redirects to `next` (default `/admin`).
 * On failure, this page is rendered with an `?err=` query string and shows
 * an inline error.
 */

import { redirect } from "next/navigation";

import { signinAction } from "./actions";

export const dynamic = "force-dynamic";

export default async function AdminLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ err?: string; next?: string }>;
}) {
  const { err, next } = await searchParams;

  // If the user is already signed in (middleware lets us through here too),
  // bounce them to /admin.
  // We can detect by reading the cookie via next/headers — but a simpler
  // check: if they came here from a successful signin redirect they'd be at
  // /admin already, so this branch only matters on direct navigation.

  async function submit(formData: FormData) {
    "use server";
    const username = String(formData.get("username") ?? "");
    const password = String(formData.get("password") ?? "");
    const nextParam = String(formData.get("next") ?? "/admin");
    const result = await signinAction(username, password);
    if (!result.ok) {
      // typedRoutes can't validate a dynamic query string; cast at the boundary.
      redirect(`/admin/login?err=${encodeURIComponent(result.error ?? "Sign-in failed")}&next=${encodeURIComponent(nextParam)}` as never);
    }
    redirect((nextParam || "/admin") as never);
  }

  return (
    <main className="mx-auto max-w-sm px-6 py-24">
      <header className="mb-8">
        <p className="text-sm uppercase tracking-widest text-neutral-500">Operator</p>
        <h1 className="mt-2 text-2xl font-semibold">Admin sign in</h1>
      </header>

      {err && (
        <p className="mb-4 text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2">
          {err}
        </p>
      )}

      <form action={submit} className="space-y-4">
        <input type="hidden" name="next" value={next ?? "/admin"} />

        <label className="block">
          <span className="block text-sm font-medium text-neutral-700 mb-1">Username</span>
          <input
            name="username"
            type="text"
            autoComplete="username"
            required
            autoFocus
            className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-400"
          />
        </label>

        <label className="block">
          <span className="block text-sm font-medium text-neutral-700 mb-1">Password</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-400"
          />
        </label>

        <button
          type="submit"
          className="w-full rounded bg-neutral-900 text-white text-sm font-medium px-4 py-2 hover:bg-neutral-700 transition-colors"
        >
          Sign in
        </button>
      </form>
    </main>
  );
}
