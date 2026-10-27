/** A card with its post, and a site that has them, for the tests. */
import { CATEGORIES, POST } from "@/post/fixtures";
import { fakeSite, INFO, type Sent } from "@/test-utils";

const SUMMARY = {
  name: "Mira Vell",
  creator: "Ann Marie",
  spec: "v3",
  format: "charx",
  greetingCount: 3,
  lorebookEntryCount: 25,
};

function entry(i: number, extra: Record<string, unknown> = {}) {
  return {
    keys: [`key${i}`],
    secondaryKeys: [],
    content: `Content of entry ${i}.`,
    enabled: true,
    order: i,
    name: `Entry name ${i}`,
    comment: "",
    constant: false,
    selective: false,
    caseSensitive: null,
    useRegex: null,
    position: null,
    priority: null,
    id: i,
    extensions: {},
    ...extra,
  };
}

export const CARD = {
  postId: 5,
  spec: "v3",
  format: "charx",
  name: "Mira Vell",
  description: "Keeper of the *Gullrock* light.",
  personality: "Dry, patient. Warms slowly to {{user}}.",
  scenario: "",
  firstMessage: "The lamp is already lit.",
  alternateGreetings: [
    "A knock at four in the morning.",
    "",
    "The supply boat is late.",
  ],
  exampleMessages:
    "<START>\n{{user}}: Who are you?\n{{char}}: The keeper.\n<START>\n{{char}}: *She writes.*",
  creatorNotes: 'Made for the contest. <div class="note">Read me</div>',
  systemPrompt: "",
  postHistoryInstructions: "",
  tags: ["fantasy", "slow-burn"],
  creator: "Ann Marie",
  characterVersion: "1.4",
  lorebook: {
    name: "The Gullrock Ledger",
    description: "",
    scanDepth: 4,
    tokenBudget: 2048,
    recursiveScanning: null,
    extensions: {},
    entries: Array.from({ length: 25 }, (_, i) =>
      entry(i, i === 0 ? { constant: true } : i === 1 ? { enabled: false } : {}),
    ),
  },
};

/** A site with post 5 and its card, and whatever else a test needs. */
export function cardSite({
  card = CARD as unknown,
  summary = SUMMARY as unknown,
  modules = ["cards"],
  post = {},
}: {
  card?: unknown;
  summary?: unknown;
  modules?: string[];
  /** more of the post, or other values */
  post?: Record<string, unknown>;
} = {}) {
  return fakeSite({
    "GET /info": { body: { ...INFO, modules } },
    "GET /post/5": (sent: Sent) => ({
      body: {
        ...POST,
        ...post,
        card: sent.path.includes("card") ? summary : undefined,
      },
    }),
    "GET /post/5/around": { body: { prev: null, next: null } },
    "GET /tag-categories": { body: CATEGORIES },
    "GET /modules/cards/post/5": { body: card },
  } as never);
}
