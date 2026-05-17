/**
 * Server Actions for the admin login page.
 *
 * signinAction(username, password) validates creds via lib/admin_auth.ts.
 * On success, sets the signed session cookie. Returns ok/error so the
 * calling page can redirect.
 *
 * signoutAction() clears the cookie. Called from the admin header logout link.
 */

"use server";

import { cookies } from "next/headers";

import {
  ADMIN_COOKIE_NAME,
  signin,
  signoutCookie,
} from "@/lib/admin_auth";
import type { SigninResult } from "@/lib/admin_auth";

export async function signinAction(
  username: string,
  password: string,
): Promise<SigninResult> {
  const result = signin(username, password);
  if (!result.ok || !result.cookie) return result;

  const c = await cookies();
  c.set(result.cookie.name, result.cookie.value, {
    httpOnly: result.cookie.httpOnly,
    secure: result.cookie.secure,
    sameSite: result.cookie.sameSite,
    path: result.cookie.path,
    maxAge: result.cookie.maxAge,
  });
  return { ok: true };
}

export async function signoutAction(): Promise<void> {
  const clear = signoutCookie();
  const c = await cookies();
  c.set(clear.name, clear.value, {
    httpOnly: clear.httpOnly,
    secure: clear.secure,
    sameSite: clear.sameSite,
    path: clear.path,
    maxAge: clear.maxAge,
  });
  // Belt-and-suspenders: also delete by name.
  c.delete(ADMIN_COOKIE_NAME);
}
