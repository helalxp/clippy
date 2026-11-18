#!/usr/bin/env node
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function fail(message) {
  console.error("::error::" + message);
  process.exit(1);
}

const outputPath = process.argv[2];
if (!outputPath) {
  fail("Usage: node desktop/validate-updater-signing-key.mjs <decoded-public-key-output-path>");
}

const configPath = fileURLToPath(new URL("./src-tauri/tauri.conf.json", import.meta.url));
let config;
try {
  config = JSON.parse(readFileSync(configPath, "utf8"));
} catch (error) {
  fail("Could not parse Tauri configuration: " + error.message);
}

const encodedPublicKey = config?.plugins?.updater?.pubkey;
if (typeof encodedPublicKey !== "string" || encodedPublicKey.length === 0) {
  fail("desktop/src-tauri/tauri.conf.json is missing plugins.updater.pubkey.");
}
if (/\s/.test(encodedPublicKey)) {
  fail("The configured updater pubkey contains whitespace. Keep the outer Base64 value on one line; do not wrap or split it.");
}

const outerBytes = Buffer.from(encodedPublicKey, "base64");
if (
  outerBytes.length === 0 ||
  outerBytes.toString("base64") !== encodedPublicKey
) {
  fail("The configured updater pubkey is not canonical Base64.");
}

let minisignPublicKey;
try {
  minisignPublicKey = new TextDecoder("utf-8", { fatal: true }).decode(outerBytes);
} catch {
  fail("The configured updater pubkey does not decode to valid UTF-8 Minisign text.");
}

const lines = minisignPublicKey.replace(/\r\n/g, "\n").split("\n");
if (lines.at(-1) === "") lines.pop();
if (lines.length !== 2) {
  fail("The decoded updater public key must contain exactly a Minisign comment and one key line.");
}

const commentMatch = lines[0].match(/^untrusted comment: minisign public key: ([0-9A-Fa-f]{16})$/);
if (!commentMatch) {
  fail("The decoded updater public key has an invalid Minisign public-key comment.");
}

const keyLine = lines[1];
const keyBytes = Buffer.from(keyLine, "base64");
if (
  keyBytes.toString("base64") !== keyLine ||
  keyBytes.length !== 42 ||
  keyBytes.subarray(0, 2).toString("ascii") !== "Ed"
) {
  fail("The decoded updater public key does not contain a valid Ed25519 Minisign key payload.");
}

// Minisign stores the 64-bit key identifier little-endian in the payload,
// while its human-readable comment prints that identifier in big-endian hex.
const payloadKeyId = Buffer.from(keyBytes.subarray(2, 10)).reverse().toString("hex").toUpperCase();
if (payloadKeyId !== commentMatch[1].toUpperCase()) {
  fail("The Minisign public-key comment identifier does not match its key payload.");
}

writeFileSync(outputPath, lines.join("\n") + "\n", { encoding: "utf8", mode: 0o600 });
console.log("Validated Tauri updater public-key encoding and Minisign structure (key id " + payloadKeyId + ").");
