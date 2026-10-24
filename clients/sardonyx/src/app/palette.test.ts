/**
 * Every theme of index.css is readable: the pairs of colours that carry
 * text reach WCAG AA (a contrast ratio of 4.5 for body text). A theme is
 * any rule there that sets `--background`; what it leaves out it takes
 * from `:root`, as the page does.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// read from disk: Vitest hands a test no stylesheet's text, not even `?raw`
const css = readFileSync(path.join(import.meta.dirname, "../index.css"), "utf8");

const MINIMUM = 4.5;

// [text, background]: the roles text is drawn in, and what it is drawn on
const PAIRS: [string, string][] = [
  ["foreground", "background"],
  ["foreground", "card"],
  ["muted-foreground", "background"],
  ["muted-foreground", "card"],
  ["primary-foreground", "primary"],
  ["link", "background"],
  ["ok", "card"],
  ["warn", "card"],
  ["macro-foreground", "macro"],
  ["accent-foreground", "accent"],
  ["destructive", "card"],
];

type Properties = Map<string, string>;

/** The rules of a stylesheet that set custom properties, by selector. */
function customProperties(source: string): Map<string, Properties> {
  const rules = new Map<string, Properties>();
  const uncommented = source.replace(/\/\*[\s\S]*?\*\//g, "");
  // innermost blocks only: a selector and a body without braces
  for (const [, selector, body] of uncommented.matchAll(/([^{};]+)\{([^{}]*)\}/g)) {
    const properties: Properties = new Map();
    for (const [, name, value] of (body ?? "").matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
      properties.set(name ?? "", (value ?? "").trim());
    }
    if (properties.size > 0) {
      rules.set((selector ?? "").trim(), properties);
    }
  }
  return rules;
}

function resolve(properties: Properties, name: string, seen: string[] = []): string {
  const value = properties.get(name);
  if (value === undefined) {
    throw new Error(`--${name} is not set`);
  }
  const reference = value.match(/^var\(--([\w-]+)\)$/);
  if (!reference?.[1]) {
    return value;
  }
  if (seen.includes(name)) {
    throw new Error(`--${name} refers to itself`);
  }
  return resolve(properties, reference[1], [...seen, name]);
}

/** A CSS colour (`#rgb`, `#rrggbb` or `oklch(L C H)`) as linear sRGB. */
function linearRgb(colour: string): [number, number, number] {
  const hex = colour.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i)?.[1];
  if (hex) {
    const digits =
      hex.length === 3 ? [...hex].map((one) => one + one) : hex.match(/../g);
    const [r, g, b] = (digits ?? []).map((pair) => {
      const channel = Number.parseInt(pair, 16) / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return [r ?? 0, g ?? 0, b ?? 0];
  }
  const oklch = colour.match(/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)\s*\)$/i);
  if (oklch) {
    const lightness = Number(oklch[1]) / (oklch[2] ? 100 : 1);
    const chroma = Number(oklch[3]);
    const hue = (Number(oklch[4]) * Math.PI) / 180;
    const a = chroma * Math.cos(hue);
    const b = chroma * Math.sin(hue);
    // OKLab to linear sRGB (Björn Ottosson's matrices)
    const l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (lightness - 0.0894841775 * a - 1.291485548 * b) ** 3;
    const clamp = (value: number) => Math.min(1, Math.max(0, value));
    return [
      clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
      clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
      clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
    ];
  }
  throw new Error(
    `cannot read the colour ${colour} (use #rrggbb or oklch without alpha)`,
  );
}

function contrast(first: string, second: string): number {
  const luminance = (colour: string) => {
    const [r, g, b] = linearRgb(colour);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const [lighter, darker] = [luminance(first), luminance(second)].sort((x, y) => y - x);
  return ((lighter ?? 0) + 0.05) / ((darker ?? 0) + 0.05);
}

describe("the contrast check", () => {
  it("measures as WCAG does", () => {
    expect(contrast("#ffffff", "#000000")).toBeCloseTo(21, 5);
    expect(contrast("#fff", "#fff")).toBeCloseTo(1, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    // the same colours, written as oklch
    expect(contrast("oklch(1 0 0)", "oklch(0 0 0)")).toBeCloseTo(21, 2);
    expect(contrast("oklch(56.94% 0 0)", "#777777")).toBeCloseTo(1, 2);
  });

  it("refuses a colour it cannot read, rather than pass it", () => {
    expect(() => contrast("rebeccapurple", "#fff")).toThrow("cannot read");
  });
});

const rules = customProperties(css);
const root = rules.get(":root");
const themes = [...rules].filter(([, properties]) => properties.has("background"));

describe.each(themes)("the theme %s", (_selector, properties) => {
  const theme: Properties = new Map([...(root ?? []), ...properties]);

  it.each(PAIRS)("has %s readable on %s", (text, background) => {
    expect(
      contrast(resolve(theme, text), resolve(theme, background)),
    ).toBeGreaterThanOrEqual(MINIMUM);
  });
});

it("finds the light and the dark theme", () => {
  expect(themes.map(([selector]) => selector)).toEqual(
    expect.arrayContaining([":root", ".dark"]),
  );
});
