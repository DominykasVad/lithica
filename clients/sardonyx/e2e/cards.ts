/**
 * Character cards and pictures for the browser tests, made here: our own
 * pictures (a pattern of colours) and our own text, nothing third-party.
 * The small cards in fixtures/cards are written by `make-fixtures.ts` from
 * this; the large lorebook and the hostile ZIP are made by the tests that
 * need them.
 */
import { crc32, deflateRawSync, deflateSync } from "node:zlib";

/** A PNG of a pattern of colours, its colours from `seed`: each seed is another file. */
export function picture(seed: number, width = 96, height = 128): Buffer {
  const rows: Buffer[] = [];
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3);
    for (let x = 0; x < width; x++) {
      row[1 + x * 3] = (seed * 37 + x * 2) % 256;
      row[2 + x * 3] = (seed * 91 + y * 2) % 256;
      row[3 + x * 3] = (seed * 53 + x + y) % 256;
    }
    rows.push(row);
  }
  // the seed itself in the first pixels: no two seeds make the same file
  (rows[0] as Buffer).writeUInt32BE(seed >>> 0, 1);
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bits per channel
  header[9] = 2; // RGB
  return Buffer.concat([
    PNG_SIGNATURE,
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(rows))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

const WORDS = (
  "harbour lantern tide reef gull keeper storm shoal beacon current wreck " +
  "chart compass salt mooring signal fog channel ledger cove"
).split(" ");

function words(seed: number, count: number): string {
  return Array.from(
    { length: count },
    (_, i) => WORDS[(seed * 7 + i * 13) % WORDS.length],
  ).join(" ");
}

export interface CardText {
  name: string;
  creator: string;
  tags?: string[];
  /** alternate greetings, besides the first message */
  greetings?: number;
  /** lorebook entries; none: no lorebook */
  entries?: number;
  /** the card's description as written: HTML is kept as it is */
  description?: string;
  version?: string;
}

function entry(i: number) {
  return {
    keys: [`${WORDS[i % WORDS.length]}_${i}`],
    content: `Entry ${i}: ${words(i, 24)}.`,
    extensions: {},
    enabled: true,
    insertion_order: i,
    case_sensitive: false,
    name: `Entry ${i}`,
    priority: 10,
    id: i,
    comment: `Entry ${i}`,
    selective: false,
    secondary_keys: [],
    constant: false,
    position: "before_char",
  };
}

/** The `data` of a V2 or V3 card. */
function data(text: CardText) {
  return {
    name: text.name,
    description: text.description ?? `${text.name} keeps the ${words(1, 6)}.`,
    personality: words(2, 8),
    scenario: words(3, 10),
    first_mes: `${text.name} looks up from the ${words(4, 3)}.`,
    mes_example: "",
    creator_notes: `Made for the browser tests of Lithica.`,
    system_prompt: "",
    post_history_instructions: "",
    alternate_greetings: Array.from(
      { length: text.greetings ?? 2 },
      (_, i) => `Greeting ${i + 2}: ${words(i + 5, 8)}.`,
    ),
    character_book:
      text.entries === undefined
        ? undefined
        : {
            name: `${text.name}'s world`,
            entries: Array.from({ length: text.entries }, (_, i) => entry(i)),
            extensions: {},
          },
    tags: text.tags ?? ["e2e"],
    creator: text.creator,
    character_version: text.version ?? "1.0",
    extensions: {},
  };
}

export function v2Card(text: CardText) {
  return { spec: "chara_card_v2", spec_version: "2.0", data: data(text) };
}

export function v3Card(text: CardText) {
  return {
    spec: "chara_card_v3",
    spec_version: "3.0",
    data: {
      ...data(text),
      group_only_greetings: [],
      assets: [{ type: "icon", uri: "ccdefault:", name: "main", ext: "png" }],
    },
  };
}

function textChunk(keyword: string, json: unknown): Buffer {
  const encoded = Buffer.from(JSON.stringify(json)).toString("base64");
  return chunk("tEXt", Buffer.from(`${keyword}\0${encoded}`, "latin1"));
}

/** A PNG card: the picture, with the card in a `chara` (V2) or `ccv3` (V3) chunk. */
export function pngCard(card: { spec: string }, seed: number): Buffer {
  const png = picture(seed);
  const end = png.length - 12; // the IEND chunk
  const keyword = card.spec === "chara_card_v3" ? "ccv3" : "chara";
  return Buffer.concat([
    png.subarray(0, end),
    textChunk(keyword, card),
    png.subarray(end),
  ]);
}

interface ZipEntry {
  name: string;
  data: Buffer;
  /** deflated (8) or stored (0) */
  method?: 0 | 8;
}

/** A ZIP file of these entries. */
export function zip(entries: ZipEntry[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const one of entries) {
    const method = one.method ?? 8;
    const body = method === 8 ? deflateRawSync(one.data) : one.data;
    const name = Buffer.from(one.name);
    const crc = crc32(one.data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(body.length, 18);
    local.writeUInt32LE(one.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(method, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(body.length, 20);
    central.writeUInt32LE(one.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, name, body);
    centrals.push(central, name);
    offset += local.length + name.length + body.length;
  }
  const directory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, end]);
}

/** A CHARX card: its card.json and its icon. */
export function charxCard(card: ReturnType<typeof v3Card>, seed: number): Buffer {
  const withIcon = {
    ...card,
    data: {
      ...card.data,
      assets: [
        {
          type: "icon",
          uri: "embeded://assets/icon/images/main.png",
          name: "main",
          ext: "png",
        },
      ],
    },
  };
  return zip([
    { name: "card.json", data: Buffer.from(JSON.stringify(withIcon)) },
    { name: "assets/icon/images/main.png", data: picture(seed), method: 0 },
  ]);
}

/**
 * A CHARX that is a ZIP bomb: one entry of 10 MB of zeros, a few kilobytes
 * packed. The site must refuse it.
 */
export function zipBomb(): Buffer {
  const card = v3Card({ name: "Bomb", creator: "e2e" });
  return zip([
    { name: "card.json", data: Buffer.from(JSON.stringify(card)) },
    { name: "assets/other/zeros.bin", data: Buffer.alloc(10 * 1024 * 1024) },
  ]);
}
