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

function toArrayBuffer(value: Uint8Array): ArrayBuffer {
  return value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer;
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
  return crypto.subtle.verify("HMAC", key, toArrayBuffer(fromBase64Url(signature)), encoder.encode(payload));
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

interface Tlv {
  tag: number;
  start: number;
  headerLength: number;
  length: number;
  end: number;
  valueStart: number;
  valueEnd: number;
}

interface ParsedAlexaCert {
  der: Uint8Array;
  spki: Uint8Array;
  notBefore: Date;
  notAfter: Date;
  dnsNames: string[];
}

function readDerLength(bytes: Uint8Array, offset: number): { length: number; bytesRead: number } {
  const first = bytes[offset];
  if (first < 0x80) return { length: first, bytesRead: 1 };
  const count = first & 0x7f;
  if (count === 0 || count > 4) throw new Error("unsupported-der-length");
  let length = 0;
  for (let i = 0; i < count; i += 1) {
    length = (length << 8) | bytes[offset + 1 + i];
  }
  return { length, bytesRead: 1 + count };
}

function readTlv(bytes: Uint8Array, offset: number): Tlv {
  if (offset >= bytes.length) throw new Error("invalid-der-offset");
  const tag = bytes[offset];
  const { length, bytesRead } = readDerLength(bytes, offset + 1);
  const headerLength = 1 + bytesRead;
  const valueStart = offset + headerLength;
  const valueEnd = valueStart + length;
  if (valueEnd > bytes.length) throw new Error("invalid-der-length");
  return {
    tag,
    start: offset,
    headerLength,
    length,
    end: valueEnd,
    valueStart,
    valueEnd,
  };
}

function getChildren(bytes: Uint8Array, tlv: Tlv): Tlv[] {
  const out: Tlv[] = [];
  let cursor = tlv.valueStart;
  while (cursor < tlv.valueEnd) {
    const child = readTlv(bytes, cursor);
    out.push(child);
    cursor = child.end;
  }
  if (cursor !== tlv.valueEnd) throw new Error("invalid-der-children");
  return out;
}

function decodeOid(bytes: Uint8Array): string {
  if (!bytes.length) return "";
  const first = bytes[0];
  const parts = [Math.floor(first / 40), first % 40];
  let value = 0;
  for (let i = 1; i < bytes.length; i += 1) {
    value = (value << 7) | (bytes[i] & 0x7f);
    if ((bytes[i] & 0x80) === 0) {
      parts.push(value);
      value = 0;
    }
  }
  return parts.join(".");
}

function parseAsn1Time(bytes: Uint8Array, tag: number): Date {
  const text = new TextDecoder().decode(bytes);
  if (tag === 0x17) {
    // UTCTime: YYMMDDHHMMSSZ
    const yy = Number(text.slice(0, 2));
    const year = yy >= 50 ? 1900 + yy : 2000 + yy;
    const mm = Number(text.slice(2, 4));
    const dd = Number(text.slice(4, 6));
    const hh = Number(text.slice(6, 8));
    const mi = Number(text.slice(8, 10));
    const ss = Number(text.slice(10, 12));
    return new Date(Date.UTC(year, mm - 1, dd, hh, mi, ss));
  }
  if (tag === 0x18) {
    // GeneralizedTime: YYYYMMDDHHMMSSZ
    const year = Number(text.slice(0, 4));
    const mm = Number(text.slice(4, 6));
    const dd = Number(text.slice(6, 8));
    const hh = Number(text.slice(8, 10));
    const mi = Number(text.slice(10, 12));
    const ss = Number(text.slice(12, 14));
    return new Date(Date.UTC(year, mm - 1, dd, hh, mi, ss));
  }
  throw new Error("unsupported-time-tag");
}

function pemToDer(pem: string): Uint8Array {
  const b64 = pem
    .replace(/-----BEGIN CERTIFICATE-----/g, "")
    .replace(/-----END CERTIFICATE-----/g, "")
    .replace(/\s+/g, "");
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

function parsePemCertificates(chainPem: string): Uint8Array[] {
  const matches = chainPem.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) ?? [];
  return matches.map((pem) => pemToDer(pem));
}

function parseCertificate(der: Uint8Array): ParsedAlexaCert {
  const root = readTlv(der, 0);
  if (root.tag !== 0x30 || root.end !== der.length) throw new Error("invalid-certificate-der");
  const rootChildren = getChildren(der, root);
  if (!rootChildren.length) throw new Error("invalid-certificate-structure");

  const tbs = rootChildren[0];
  const tbsChildren = getChildren(der, tbs);
  const versionOffset = tbsChildren[0]?.tag === 0xa0 ? 1 : 0;
  const validity = tbsChildren[versionOffset + 3];
  const subjectPublicKeyInfo = tbsChildren[versionOffset + 5];
  if (!validity || !subjectPublicKeyInfo) throw new Error("missing-certificate-fields");

  const validityChildren = getChildren(der, validity);
  if (validityChildren.length < 2) throw new Error("invalid-validity");
  const notBeforeTlv = validityChildren[0];
  const notAfterTlv = validityChildren[1];
  const notBefore = parseAsn1Time(der.slice(notBeforeTlv.valueStart, notBeforeTlv.valueEnd), notBeforeTlv.tag);
  const notAfter = parseAsn1Time(der.slice(notAfterTlv.valueStart, notAfterTlv.valueEnd), notAfterTlv.tag);

  const dnsNames: string[] = [];
  for (let i = versionOffset + 6; i < tbsChildren.length; i += 1) {
    const extContainer = tbsChildren[i];
    if (extContainer.tag !== 0xa3) continue;
    const extSets = getChildren(der, extContainer);
    if (!extSets.length) continue;
    const extList = getChildren(der, extSets[0]);

    for (const ext of extList) {
      const extParts = getChildren(der, ext);
      if (extParts.length < 2) continue;
      const oidPart = extParts[0];
      if (oidPart.tag !== 0x06) continue;
      const oid = decodeOid(der.slice(oidPart.valueStart, oidPart.valueEnd));
      if (oid !== "2.5.29.17") continue;
      const valuePart = extParts[extParts.length - 1];
      if (valuePart.tag !== 0x04) continue;

      const sanDer = der.slice(valuePart.valueStart, valuePart.valueEnd);
      const sanRoot = readTlv(sanDer, 0);
      const sanChildren = getChildren(sanDer, sanRoot);
      for (const name of sanChildren) {
        if (name.tag === 0x82) {
          dnsNames.push(new TextDecoder().decode(sanDer.slice(name.valueStart, name.valueEnd)).toLowerCase());
        }
      }
    }
  }

  return {
    der,
    spki: der.slice(subjectPublicKeyInfo.start, subjectPublicKeyInfo.end),
    notBefore,
    notAfter,
    dnsNames,
  };
}

async function importRsaSpki(spkiDer: Uint8Array): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "spki",
    toArrayBuffer(spkiDer),
    {
      name: "RSASSA-PKCS1-v1_5",
      hash: "SHA-1",
    },
    false,
    ["verify"],
  );
}

export async function verifyAlexaRequestSignature(
  certChainUrl: string,
  signatureHeader: string,
  rawBody: ArrayBuffer,
): Promise<{ ok: boolean; reason?: string }> {
  if (!validateAlexaCertChainUrl(certChainUrl)) {
    return { ok: false, reason: "invalid-cert-chain-url" };
  }

  const signature = fromBase64Url(signatureHeader.trim());

  let certResponse: Response;
  try {
    certResponse = await fetch(certChainUrl, { method: "GET" });
  } catch {
    return { ok: false, reason: "cert-fetch-failed" };
  }

  if (!certResponse.ok) {
    return { ok: false, reason: `cert-fetch-status-${certResponse.status}` };
  }

  const certPem = await certResponse.text();
  const certs = parsePemCertificates(certPem);
  if (!certs.length) {
    return { ok: false, reason: "empty-cert-chain" };
  }

  let leaf: ParsedAlexaCert;
  try {
    leaf = parseCertificate(certs[0]);
  } catch {
    return { ok: false, reason: "invalid-leaf-certificate" };
  }

  const now = Date.now();
  if (leaf.notBefore.getTime() > now || leaf.notAfter.getTime() < now) {
    return { ok: false, reason: "certificate-not-valid-now" };
  }

  const hasAlexaSan = leaf.dnsNames.some((name) => name === "echo-api.amazon.com");
  if (!hasAlexaSan) {
    return { ok: false, reason: "certificate-san-missing-echo-api" };
  }

  let publicKey: CryptoKey;
  try {
    publicKey = await importRsaSpki(leaf.spki);
  } catch {
    return { ok: false, reason: "invalid-certificate-public-key" };
  }

  const verified = await crypto.subtle.verify(
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-1" },
    publicKey,
    toArrayBuffer(signature),
    rawBody,
  );

  if (!verified) {
    return { ok: false, reason: "signature-verification-failed" };
  }

  return { ok: true };
}
