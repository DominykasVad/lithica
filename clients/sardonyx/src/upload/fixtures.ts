/**
 * Card files and a stand-in for XMLHttpRequest, for the upload tests.
 */

const encoder = new TextEncoder();

function u32(value: number): number[] {
  return [(value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255];
}

function le(value: number, size: 2 | 4): number[] {
  return Array.from({ length: size }, (_, i) => (value >>> (8 * i)) & 255);
}

function chunk(type: string, data: Uint8Array): number[] {
  // the CRC is not read by the client: zeros do
  return [...u32(data.length), ...encoder.encode(type), ...data, 0, 0, 0, 0];
}

function card(tags: unknown): string {
  return JSON.stringify({ spec: "chara_card_v2", data: { name: "Probe", tags } });
}

/**
 * A PNG with a V2 card in its `chara` chunk (or a `ccv3` one); `padding`
 * empty chunks before it; `overlong`, a last chunk that says it is longer
 * than the file.
 */
export function pngCard(
  tags: unknown,
  keyword: "chara" | "ccv3" = "chara",
  { padding = 0, overlong = false }: { padding?: number; overlong?: boolean } = {},
): Uint8Array {
  const text = new Uint8Array([
    ...encoder.encode(keyword),
    0,
    ...encoder.encode(btoa(card(tags))),
  ]);
  const empty = chunk("zzZz", new Uint8Array());
  const parts = [
    [137, 80, 78, 71, 13, 10, 26, 10],
    chunk("IHDR", new Uint8Array(13)),
    ...Array.from({ length: padding }, () => empty),
    ...(overlong ? [[...u32(1_000_000), ...encoder.encode("zzZz"), 1, 2, 3]] : []),
    chunk("tEXt", text),
    chunk("IEND", new Uint8Array()),
  ];
  const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of parts) {
    out.set(part, at);
    at += part.length;
  }
  return out;
}

async function deflate(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Response(data as BodyInit).body?.pipeThrough(
    new CompressionStream("deflate-raw"),
  );
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** A CHARX (a ZIP) with `card.json`, stored or deflated, and another entry. */
export async function charxCard(
  tags: unknown,
  { deflated = true, declaredSize }: { deflated?: boolean; declaredSize?: number } = {},
): Promise<Uint8Array> {
  const files: [string, Uint8Array, boolean][] = [
    ["assets/icon.txt", encoder.encode("not a picture"), false],
    ["card.json", encoder.encode(card(tags)), deflated],
  ];
  const local: number[] = [];
  const central: number[] = [];
  for (const [name, raw, compress] of files) {
    const data = compress ? await deflate(raw) : raw;
    const nameBytes = encoder.encode(name);
    const offset = local.length;
    const size = declaredSize ?? raw.length;
    local.push(
      ...le(0x04034b50, 4),
      ...le(20, 2),
      ...le(0, 2),
      ...le(compress ? 8 : 0, 2),
      ...le(0, 4),
      ...le(0, 4),
      ...le(data.length, 4),
      ...le(size, 4),
      ...le(nameBytes.length, 2),
      ...le(0, 2),
      ...nameBytes,
      ...data,
    );
    central.push(
      ...le(0x02014b50, 4),
      ...le(20, 2),
      ...le(20, 2),
      ...le(0, 2),
      ...le(compress ? 8 : 0, 2),
      ...le(0, 4),
      ...le(0, 4),
      ...le(data.length, 4),
      ...le(size, 4),
      ...le(nameBytes.length, 2),
      ...le(0, 2),
      ...le(0, 2),
      ...le(0, 2),
      ...le(0, 2),
      ...le(0, 4),
      ...le(offset, 4),
      ...nameBytes,
    );
  }
  const end = [
    ...le(0x06054b50, 4),
    ...le(0, 2),
    ...le(0, 2),
    ...le(files.length, 2),
    ...le(files.length, 2),
    ...le(central.length, 4),
    ...le(local.length, 4),
    ...le(0, 2),
  ];
  return new Uint8Array([...local, ...central, ...end]);
}

/** A stand-in for XMLHttpRequest: each request is kept, and the test answers it. */
export class FakeXhr {
  static all: FakeXhr[] = [];
  method = "";
  url = "";
  headers: Record<string, string> = {};
  body: FormData | null = null;
  status = 0;
  statusText = "";
  responseText = "";
  aborted = false;
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = {
    onprogress: null,
  };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send(body: FormData) {
    this.body = body;
    FakeXhr.all.push(this);
  }

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  /** the file in the request */
  get file(): File {
    return this.body?.get("content") as File;
  }

  progress(loaded: number, total: number) {
    this.upload.onprogress?.({
      lengthComputable: true,
      loaded,
      total,
    } as ProgressEvent);
  }

  respond(status: number, body: unknown, statusText = "") {
    this.status = status;
    this.statusText = statusText;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }

  fail() {
    this.onerror?.();
  }
}
