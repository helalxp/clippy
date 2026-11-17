import { timingSafeEqual } from "node:crypto";

/** Constant-time comparison for the per-launch local desktop API secret. */
export function isAuthorizedToken(supplied: string, expected: string): boolean {
  if (!supplied || !expected) return false;
  const suppliedBytes = Buffer.from(supplied, "utf8");
  const expectedBytes = Buffer.from(expected, "utf8");
  if (suppliedBytes.length !== expectedBytes.length) return false;
  return timingSafeEqual(suppliedBytes, expectedBytes);
}
