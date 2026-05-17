/**
 * Middleware: gate everything under /admin behind the admin_session cookie.
 *
 * Runs at the Edge before any page handler. If the cookie is missing or
 * invalid, we redirect to /admin/login (preserving the original URL in a
 * `next` query param so we can come back after sign-in).
 *
 * Note: this middleware does NOT call lib/admin_auth.ts. The Edge runtime
 * doesn't include node:crypto's full API, so we ship a tiny WebCrypto
 * verifier here. The auth library handles all crypto in Node server
 * components / Server Actions.
 */

import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = "admin_session";
const LOGIN_PATH = "/admin/login";

async function verifyEdge(token: string, secret: string): Promise<boolean> {
  const dot = token.indexOf(".");
  if (dot <= 0) return false;
  const body = token.slice(0, dot);
  const sigB64u = token.slice(dot + 1);

  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  const sig = b64uToBytes(sigB64u);
  // TS5+ narrows BufferSource to ArrayBuffer-backed buffers; our Uint8Array
  // is fine at runtime but the type narrows wider — cast at the boundary.
  const valid = await crypto.subtle.verify(
    "HMAC",
    key,
    sig as BufferSource,
    enc.encode(body),
  );
  if (!valid) return false;

  // Also enforce the exp claim at the edge so an expired-but-validly-signed
  // cookie still gets rejected.
  try {
    const padded = body.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (body.length % 4)) % 4);
    const payloadJson = atob(padded);
    const payload = JSON.parse(payloadJson) as { exp?: number };
    const now = Math.floor(Date.now() / 1000);
    if (typeof payload.exp !== "number" || payload.exp < now) return false;
  } catch {
    return false;
  }

  return true;
}

function b64uToBytes(s: string): Uint8Array {
  const padded = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export async function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  // Allow the login page itself (and its Server Action endpoint) through.
  if (pathname === LOGIN_PATH) return NextResponse.next();

  const token = req.cookies.get(COOKIE_NAME)?.value;
  const secret = process.env.ADMIN_SESSION_SECRET;
  if (!secret) {
    // Config error: surface a clear 500 rather than silently letting people in.
    return new NextResponse(
      "ADMIN_SESSION_SECRET not configured. Set it in .env.local.",
      { status: 500 },
    );
  }

  const ok = token ? await verifyEdge(token, secret) : false;
  if (ok) return NextResponse.next();

  // Redirect to login, remembering where we were.
  const url = req.nextUrl.clone();
  url.pathname = LOGIN_PATH;
  url.search = "";
  if (pathname !== "/admin") {
    url.searchParams.set("next", pathname + search);
  }
  return NextResponse.redirect(url);
}

export const config = {
  // Apply to /admin and everything under it. Other routes (/, /trends,
  // /methodology, /brief/[id]) are public, no middleware.
  matcher: ["/admin", "/admin/:path*"],
};
