import { Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { LibrarySearch } from "@/library/search";
import type { Card } from "@/post/queries";
import {
  CardText,
  examples,
  TextModeProvider,
  TextModeSwitch,
  useTextMode,
} from "@/text/CardText";
import { CardImages, ImagesBar } from "@/text/StyledFrame";
import { imageHosts } from "@/text/styled";
import { EntryRow } from "./EntryRow";
import { cardTexts, countsOf, formatNumber } from "./lorebook";

// how many lorebook entries the tab shows before the lorebook page
const PREVIEW_ENTRIES = 20;

const blank = (text: string | undefined) => !text?.trim();

/** The greetings of a card: its first message, then the alternate ones. */
export function greetingsOf(card: Card): { title: string; text: string }[] {
  return [
    { title: "First message", text: card.firstMessage ?? "" },
    ...(card.alternateGreetings ?? []).map((text) => ({
      title: "Alternate greeting",
      text,
    })),
  ].filter((greeting) => !blank(greeting.text));
}

export interface Tab {
  id: string;
  label: string;
}

/** The tabs this card has something for, in their order. */
export function tabsOf(card: Card): Tab[] {
  const greetings = greetingsOf(card).length;
  const entries = card.lorebook?.entries?.length ?? 0;
  const tabs: [Tab, boolean][] = [
    [
      { id: "overview", label: "Overview" },
      [card.description, card.personality, card.scenario].some((one) => !blank(one)),
    ],
    [{ id: "greetings", label: `Greetings (${greetings})` }, greetings > 0],
    [{ id: "examples", label: "Examples" }, !blank(card.exampleMessages)],
    [{ id: "notes", label: "Creator notes" }, !blank(card.creatorNotes)],
    [
      { id: "prompts", label: "Prompts" },
      !blank(card.systemPrompt) || !blank(card.postHistoryInstructions),
    ],
    [{ id: "lorebook", label: `Lorebook (${entries})` }, entries > 0],
  ];
  return tabs.filter(([, shown]) => shown).map(([tab]) => tab);
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-semibold font-serif text-xl">{title}</h2>
      {children}
    </section>
  );
}

/** Fields of the card under their titles, those that are not empty. */
function Fields({ fields }: { fields: [string, string | undefined][] }) {
  return (
    <div className="flex flex-col gap-7">
      {fields
        .filter(([, text]) => !blank(text))
        .map(([title, text]) => (
          <Section key={title} title={title}>
            <CardText text={text ?? ""} className="text-base leading-relaxed" />
          </Section>
        ))}
    </div>
  );
}

function Greetings({ card }: { card: Card }) {
  const greetings = greetingsOf(card);
  const [shown, setShown] = useState(0);
  const at = Math.min(shown, greetings.length - 1);
  const greeting = greetings[at];
  if (!greeting) {
    return null;
  }
  const step = (by: number) =>
    setShown((at + by + greetings.length) % greetings.length);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-semibold font-serif text-xl">{greeting.title}</h2>
        <span className="text-muted-foreground text-sm">
          {at + 1} of {greetings.length}
        </span>
        {greetings.length > 1 ? (
          <span className="ml-auto flex gap-2">
            <Button
              variant="outline"
              size="icon"
              aria-label="Previous greeting"
              onClick={() => step(-1)}
            >
              <ArrowLeft />
            </Button>
            <Button
              variant="outline"
              size="icon"
              aria-label="Next greeting"
              onClick={() => step(1)}
            >
              <ArrowRight />
            </Button>
          </span>
        ) : null}
      </div>
      <CardText
        text={greeting.text}
        className="rounded-xl bg-background px-6 py-5 text-base leading-relaxed"
      />
    </div>
  );
}

function Examples({ text }: { text: string }) {
  return (
    <Section title="Example messages">
      <div className="flex flex-col gap-4">
        {examples(text).map((dialogue, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: the dialogues in order
          <div key={i} className="flex flex-col gap-1.5">
            {/* the marker the card splits them with, shown as it is written */}
            <span className="font-mono text-muted-foreground text-xs">{"<START>"}</span>
            <CardText
              text={dialogue}
              className="rounded-xl bg-background px-5 py-4 leading-relaxed"
            />
          </div>
        ))}
      </div>
    </Section>
  );
}

function LorebookTab({
  card,
  postId,
  from,
}: {
  card: Card;
  postId: number;
  from: LibrarySearch;
}) {
  const lorebook = card.lorebook;
  const entries = lorebook?.entries ?? [];
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());
  const counts = countsOf(entries);
  const facts = [
    `${formatNumber(counts.entries)} entries`,
    `${formatNumber(counts.constant)} always active`,
    `${formatNumber(counts.disabled)} disabled`,
    lorebook?.scanDepth == null ? null : `scan depth ${lorebook.scanDepth}`,
    lorebook?.tokenBudget == null ? null : `token budget ${lorebook.tokenBudget}`,
  ].filter(Boolean);
  const toggle = (index: number) =>
    setOpen((current) => {
      const next = new Set(current);
      if (!next.delete(index)) {
        next.add(index);
      }
      return next;
    });
  return (
    <div className="flex flex-col gap-3.5">
      <h2 className="font-semibold font-serif text-xl">
        {lorebook?.name || "Lorebook"}
      </h2>
      <p className="text-muted-foreground">{facts.join(" · ")}</p>
      <div className="rounded-xl border [&>*:last-child]:border-b-0">
        {entries.slice(0, PREVIEW_ENTRIES).map((entry, index) => (
          <EntryRow
            // biome-ignore lint/suspicious/noArrayIndexKey: an entry's place is what keys it
            key={index}
            numbered={{ index, entry }}
            open={open.has(index)}
            onToggle={() => toggle(index)}
          />
        ))}
      </div>
      <Link
        to="/posts/$id/lorebook"
        params={{ id: String(postId) }}
        search={from}
        className="font-medium text-link underline-offset-4 hover:underline"
      >
        Open the full lorebook ({formatNumber(entries.length)} entries) →
      </Link>
    </div>
  );
}

/**
 * The card of a post, a tab for each part of it that has something. The
 * tab is part of the URL; one the card has nothing for shows the first.
 */
export function CardViewer({
  card,
  postId,
  tab,
  onTab,
  from,
}: {
  card: Card;
  postId: number;
  tab: string | undefined;
  onTab(tab: string): void;
  from: LibrarySearch;
}) {
  const [mode, setMode] = useTextMode();
  // the card's pictures load in Styled only when asked, for this card only
  // (the viewer is made anew for another card)
  const [images, setImages] = useState(false);
  const hosts = useMemo(() => imageHosts(cardTexts(card)), [card]);
  const tabs = tabsOf(card);
  const current = tabs.find((one) => one.id === tab) ?? tabs[0];
  if (!current) {
    return <p className="p-6 text-muted-foreground">This card has no text to show.</p>;
  }
  return (
    <TextModeProvider mode={mode}>
      <CardImages allowed={images}>
        <Tabs
          value={current.id}
          onValueChange={onTab}
          className="min-w-0 rounded-2xl border bg-card"
        >
          <div className="flex flex-wrap items-end justify-between gap-2 border-b">
            <TabsList aria-label="Card sections" className="border-b-0">
              {tabs.map((one) => (
                <TabsTrigger key={one.id} value={one.id}>
                  {one.label}
                </TabsTrigger>
              ))}
            </TabsList>
            <div className="px-3 py-2">
              <TextModeSwitch mode={mode} onChange={setMode} />
            </div>
          </div>
          {mode === "styled" ? (
            <div className="border-b px-5 py-3 sm:px-9">
              <ImagesBar
                hosts={hosts}
                allowed={images}
                onAllow={() => setImages(true)}
              />
            </div>
          ) : null}
          <div className="px-5 pt-7 pb-10 sm:px-9">
            <TabsContent value="overview">
              <Fields
                fields={[
                  ["Description", card.description],
                  ["Personality", card.personality],
                  ["Scenario", card.scenario],
                ]}
              />
              <p className="mt-7 text-muted-foreground text-sm">
                Placeholders such as <span className="font-mono">{"{{user}}"}</span> are
                shown as the card writes them; the chat program fills them in.
              </p>
            </TabsContent>
            <TabsContent value="greetings">
              <Greetings card={card} />
            </TabsContent>
            <TabsContent value="examples">
              <Examples text={card.exampleMessages ?? ""} />
            </TabsContent>
            <TabsContent value="notes">
              <Fields fields={[["Creator notes", card.creatorNotes]]} />
            </TabsContent>
            <TabsContent value="prompts">
              <Fields
                fields={[
                  ["System prompt", card.systemPrompt],
                  ["Post-history instructions", card.postHistoryInstructions],
                ]}
              />
            </TabsContent>
            <TabsContent value="lorebook">
              <LorebookTab card={card} postId={postId} from={from} />
            </TabsContent>
          </div>
        </Tabs>
      </CardImages>
    </TextModeProvider>
  );
}
