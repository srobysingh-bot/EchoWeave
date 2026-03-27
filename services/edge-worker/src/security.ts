import { StreamTokenClaims } from "./types";

const encoder = new TextEncoder();

function toBase64Url(input: ArrayBuffer | Uint8Array): string {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64Url(input: string): Uint8Array {
  const padded = input.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (input.length % 4)) % 4);
  const binary = atob(padded);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

async function importHmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function hashConnectorSecret(secret: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(secret));
  return toBase64Url(digest);
}

export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let result = 0;
  for (let i = 0; i < a.length; i += 1) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return result === 0;
}

export async function signPayload(payload: string, secret: string): Promise<string> {
  const key = await importHmacKey(secret);
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(payload));
  return toBase64Url(signature);
}

export async function verifyPayloadSignature(payload: string, signature: string, secret: string): Promise<boolean> {
  const key = await importHmacKey(secret);
  return crypto.subtle.verify("HMAC", key, fromBase64Url(signature), encoder.encode(payload));
}

export async function issueSignedStreamToken(claims: StreamTokenClaims, secret: string): Promise<string> {
  const payload = JSON.stringify(claims);
  const encodedPayload = toBase64Url(encoder.encode(payload));
  const signature = await signPayload(encodedPayload, secret);
  return `${encodedPayload}.${signature}`;
}

export async function verifySignedStreamToken(token: string, secret: string): Promise<StreamTokenClaims | null> {
  const [encodedPayload, signature] = token.split(".");
  if (!encodedPayload || !signature) return null;

  const ok = await verifyPayloadSignature(encodedPayload, signature, secret);
  if (!ok) return null;

  const decoded = new TextDecoder().decode(fromBase64Url(encodedPayload));
  const claims = JSON.parse(decoded) as StreamTokenClaims;
  if (!claims.exp || claims.exp < Math.floor(Date.now() / 1000)) return null;
  return claims;
}

export function validateAlexaTimestamp(timestamp: string, maxSkewSeconds = 150): boolean {
  const ts = Date.parse(timestamp);
  if (Number.isNaN(ts)) return false;
  const skew = Math.abs(Date.now() - ts) / 1000;
  return skew <= maxSkewSeconds;
}

export function validateAlexaCertChainUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    if (parsed.hostname !== "s3.amazonaws.com") return false;
    if (!parsed.pathname.startsWith("/echo.api/")) return false;
    if (parsed.port && parsed.port !== "443") return false;
    return true;
  } catch {
    return false;
  }
}
