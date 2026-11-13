import { test } from "node:test";
import assert from "node:assert/strict";
import { isAuthorizedToken } from "./auth.js";

test("renderer token accepts only the exact active session secret", () => {
  assert.equal(isAuthorizedToken("secret", "secret"), true);
  assert.equal(isAuthorizedToken("wrong", "secret"), false);
  assert.equal(isAuthorizedToken("", "secret"), false);
  assert.equal(isAuthorizedToken("secret", ""), false);
  assert.equal(isAuthorizedToken("secret-long", "secret"), false);
});
