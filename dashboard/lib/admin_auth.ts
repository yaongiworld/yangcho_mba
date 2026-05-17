/**
 * Admin auth — simple ID/password gate for /admin.
 *
 * The session is a signed cookie (HMAC-SHA256). No database, no Supabase Auth.
 * Credentials live in dashboard/.env.local:
 *   ADMIN_USER             — username (e.g., "yangcho")
 *   ADMIN_PASS             — password
 *   ADMIN_SESSION_SECRET   — long random string for cookie signing
 *
 * Lifecycle:
 *   1. signin() compares submitted creds against env using timing-safe equal.
 *   2. On match, it issues a signed session payload and asks the caller to
 *      set it as a cookie.
 *   3. verifySessionCookie() decodes the cookie, checks the HMAC, checks
 *      the expiry, returns the user or null.
 *
 * Crypto: Node's built-in crypto. No new dependencies. The cookie value is
 * `base64url(payloadJson) + "." + base64url(hmac)`. Tampering with the
 * payload changes the HMAC; verification rejects it.
 *
 * Security caveats:
 *   - This is operator-level auth, not user auth. Yangcho is the only
 *     human in the picture; a single shared credential is fine.
 *   - Cookie is HttpOnly + Secure + SameSite=Lax. JS in the browser can't
 *     read it; cross-site requests don't carry it.
 *   - Constant-time compare avoids leaking length / prefix-match timing.
 *   - No login attempt throttling. At personal scale on an unlinked URL,
 *     brute-force is implausible. If we ever publicize the URL, add a
 *     simple rate limit (1 attempt per 2 seconds keyed on IP) here.
 */

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const COOKIE_NAME = "admin_session";
const COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 days

interface SessionPayload {
  user: string;
  iat: number; // issued-at, seconds since epoch
  exp: number; // expiry, seconds since epoch
}

export interface CookieAttributes {
  name: string;
  value: string;
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
}

function base64url(buf: Buffer | string): string {
  return Buffer.from(buf)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function fromBase64url(s: string): Buffer {
  const padded = s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4);
  return Buffer.from(padded, "base64");
}

function getSecret(): Buffer {
  const secret = process.env.ADMIN_SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error(
      "ADMIN_SESSION_SECRET not set or too short (need at least 32 chars).",
    );
  }
  return Buffer.from(secret, "utf-8");
}

function sign(payload: SessionPayload): string {
  const json = JSON.stringify(payload);
  const body = base64url(json);
  const mac = createHmac("sha256", getSecret()).update(body).digest();
  return `${body}.${base64url(mac)}`;
}

function verify(token: string): SessionPayload | null {
  const dot = token.indexOf(".");
  if (dot <= 0) return null;
  const body = token.slice(0, dot);
  const macFromCookie = fromBase64url(token.slice(dot + 1));

  const macExpected = createHmac("sha256", getSecret()).update(body).digest();
  // timingSafeEqual requires equal-length buffers; reject on mismatch.
  if (macFromCookie.length !== macExpected.length) return null;
  if (!timingSafeEqual(macFromCookie, macExpected)) return null;

  let payload: SessionPayload;
  try {
    payload = JSON.parse(fromBase64url(body).toString("utf-8")) as SessionPayload;
  } catch {
    return null;
  }
  const now = Math.floor(Date.now() / 1000);
  if (typeof payload.exp !== "number" || payload.exp < now) return null;
  if (typeof payload.user !== "string" || !payload.user) return null;
  return payload;
}

/** Constant-time string equal. Falls back to false on length mismatch. */
function ctEqual(a: string, b: string): boolean {
  // Pad both sides to the longer length so timingSafeEqual sees equal-length
  // buffers; the false branch still returns false on length mismatch.
  const aBuf = Buffer.from(a, "utf-8");
  const bBuf = Buffer.from(b, "utf-8");
  if (aBuf.length !== bBuf.length) {
    // Run the compare anyway against random bytes of equal length to keep
    // timing flat regardless of input length.
    timingSafeEqual(aBuf, randomBytes(aBuf.length));
    return false;
  }
  return timingSafeEqual(aBuf, bBuf);
}

export interface SigninResult {
  ok: boolean;
  cookie?: CookieAttributes;
  error?: string;
}

export function signin(username: string, password: string): SigninResult {
  const expectedUser = process.env.ADMIN_USER;
  const expectedPass = process.env.ADMIN_PASS;
  if (!expectedUser || !expectedPass) {
    return { ok: false, error: "Admin credentials are not configured." };
  }
  // Always compare both halves, regardless of user match, so timing doesn't
  // leak which half was wrong.
  const userOk = ctEqual(username, expectedUser);
  const passOk = ctEqual(password, expectedPass);
  if (!userOk || !passOk) {
    return { ok: false, error: "Incorrect username or password." };
  }
  const now = Math.floor(Date.now() / 1000);
  const payload: SessionPayload = {
    user: expectedUser,
    iat: now,
    exp: now + COOKIE_MAX_AGE_SECONDS,
  };
  return {
    ok: true,
    cookie: {
      name: COOKIE_NAME,
      value: sign(payload),
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "lax",
      path: "/",
      maxAge: COOKIE_MAX_AGE_SECONDS,
    },
  };
}

/** A cookie shape that, when set, clears the session. */
export function signoutCookie(): CookieAttributes {
  return {
    name: COOKIE_NAME,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  };
}

export function verifySessionCookie(value: string | undefined): { user: string } | null {
  if (!value) return null;
  const payload = verify(value);
  return payload ? { user: payload.user } : null;
}

export const ADMIN_COOKIE_NAME = COOKIE_NAME;
