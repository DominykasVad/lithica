/**
 * Whether a card file says it is NSFW: its own tags, read in the browser
 * only far enough for that. Nothing is shown or rendered of the card; any
 * file that is not a card, or that cannot be read within the limits, is
 * simply "no". The file is the user's own, about to be uploaded, but read
 * as if it were anybody's: sizes checked before anything is read or
 * inflated.
 */

const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];
// the most of a card's JSON (and of a chunk holding it) read here
const MAX_CARD_BYTES = 8 * 1024 * 1024;
// the most chunks of a PNG looked at: a card's come before its picture
const MAX_PNG_CHUNKS = 10_000;
// a CHARX's central directory is read from at most this much of its end
const MAX_DIRECTORY_BYTES = 1024 * 1024;

const NSFW = "nsfw";

async function bytes(file: Blob, start: number, end: number): Promise<Uint8Array> {
  return new Uint8Array(await file.slice(start, end).arrayBuffer());
}

const latin1 = (data: Uint8Array) => new TextDecoder("latin1").decode(data);

/** The card's tags, from its JSON of any spec: v1 has none. */
function tagsOf(json: unknown): string[] {
  if (typeof json !== "object" || json === null) {
    return [];
  }
  const record = json as { data?: { tags?: unknown }; tags?: unknown };
  const tags = record.data?.tags ?? record.tags;
  return Array.isArray(tags)
    ? tags.filter((tag): tag is string => typeof tag === "string")
    : [];
}

/** The JSON of a PNG card: its `ccv3` text chunk, else its `chara` one. */
async function pngCard(file: Blob): Promise<unknown> {
  const head = await bytes(file, 0, 8);
  if (!PNG_SIGNATURE.every((byte, i) => head[i] === byte)) {
    return null;
  }
  const found: Record<string, string> = {};
  let at = 8;
  let chunks = 0;
  while (at + 8 <= file.size) {
    // too many chunks, or one longer than the rest of the file: not read
    // any further, and not taken for a card
    if (++chunks > MAX_PNG_CHUNKS) {
      return null;
    }
    const header = await bytes(file, at, at + 8);
    const length = new DataView(header.buffer).getUint32(0);
    const type = latin1(header.subarray(4, 8));
    if (at + 12 + length > file.size) {
      return null;
    }
    if (type === "IEND") {
      break;
    }
    if (type === "tEXt" && length <= MAX_CARD_BYTES) {
      const body = await bytes(file, at + 8, at + 8 + length);
      const zero = body.indexOf(0);
      const keyword = zero > 0 ? latin1(body.subarray(0, zero)).toLowerCase() : "";
      if (keyword === "ccv3" || keyword === "chara") {
        found[keyword] = latin1(body.subarray(zero + 1));
      }
    }
    at += 12 + length;
  }
  const text = found.ccv3 ?? found.chara;
  if (!text) {
    return null;
  }
  // base64 of UTF-8 JSON
  const raw = Uint8Array.from(atob(text.trim()), (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(raw));
}

/** At most `limit` bytes of a raw deflate stream, inflated; null beyond it. */
async function inflate(data: Uint8Array, limit: number): Promise<Uint8Array | null> {
  const source = new Response(data as BodyInit).body;
  if (!source) {
    return null;
  }
  const stream = source.pipeThrough(new DecompressionStream("deflate-raw"));
  const reader = stream.getReader();
  const parts: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    total += value.length;
    if (total > limit) {
      await reader.cancel();
      return null;
    }
    parts.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

/** The JSON of a CHARX card: its `card.json`, found by the ZIP's directory. */
async function charxCard(file: Blob): Promise<unknown> {
  const tailStart = Math.max(0, file.size - MAX_DIRECTORY_BYTES);
  const tail = await bytes(file, tailStart, file.size);
  const view = new DataView(tail.buffer);
  // the end of central directory record, the last one in the file
  let end = -1;
  for (let i = tail.length - 22; i >= 0; i--) {
    if (view.getUint32(i, true) === 0x06054b50) {
      end = i;
      break;
    }
  }
  if (end < 0) {
    return null;
  }
  const entries = view.getUint16(end + 10, true);
  const size = view.getUint32(end + 12, true);
  const offset = view.getUint32(end + 16, true);
  // zip64, or a directory beyond what was read: not looked into
  if (offset === 0xffffffff || offset < tailStart || offset + size > file.size) {
    return null;
  }
  let at = offset - tailStart;
  for (let n = 0; n < entries && at + 46 <= tail.length; n++) {
    if (view.getUint32(at, true) !== 0x02014b50) {
      return null;
    }
    const method = view.getUint16(at + 10, true);
    const compressed = view.getUint32(at + 20, true);
    const uncompressed = view.getUint32(at + 24, true);
    const nameLength = view.getUint16(at + 28, true);
    const extraLength = view.getUint16(at + 30, true);
    const commentLength = view.getUint16(at + 32, true);
    const local = view.getUint32(at + 42, true);
    const name = new TextDecoder().decode(tail.subarray(at + 46, at + 46 + nameLength));
    if (name === "card.json") {
      if (compressed > MAX_CARD_BYTES || uncompressed > MAX_CARD_BYTES) {
        return null;
      }
      const header = await bytes(file, local, local + 30);
      const headerView = new DataView(header.buffer);
      if (headerView.getUint32(0, true) !== 0x04034b50) {
        return null;
      }
      const start =
        local + 30 + headerView.getUint16(26, true) + headerView.getUint16(28, true);
      const data = await bytes(file, start, start + compressed);
      const json =
        method === 0 ? data : method === 8 ? await inflate(data, MAX_CARD_BYTES) : null;
      return json ? JSON.parse(new TextDecoder().decode(json)) : null;
    }
    at += 46 + nameLength + extraLength + commentLength;
  }
  return null;
}

/** Whether the file is a card (PNG or CHARX) whose own tags include NSFW. */
export async function cardSaysNsfw(file: File): Promise<boolean> {
  try {
    const name = file.name.toLowerCase();
    const card = name.endsWith(".charx") ? await charxCard(file) : await pngCard(file);
    return tagsOf(card).some((tag) => tag.trim().toLowerCase() === NSFW);
  } catch {
    // not a card, or not one this can read: the box starts unchecked
    return false;
  }
}
