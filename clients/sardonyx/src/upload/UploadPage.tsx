import { useQuery } from "@tanstack/react-query";
import { Link, useBlocker } from "@tanstack/react-router";
import { FileUp, RotateCcw, X } from "lucide-react";
import { type DragEvent, useEffect, useId, useRef, useState } from "react";
import { infoQuery } from "@/app/info";
import { uploadRank, useCanUpload } from "@/app/privileges";
import { useAuth } from "@/auth/AuthProvider";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import { CompletionInput } from "@/search/CompletionInput";
import { cardSaysNsfw } from "./cardTags";
import { formatBytes, refusal } from "./files";
import { type Batch, type Outcome, send } from "./send";

/** Files sent at the same time. */
export const PARALLEL = 2;
/** The tag a NSFW post carries (a site setting later, 5.6b). */
export const NSFW_TAG = "nsfw";

const SAFETIES = ["safe", "sketchy", "unsafe"] as const;
const SAFETY_LABELS = { safe: "Safe", sketchy: "Sketchy", unsafe: "Unsafe" } as const;

type Step = "ready" | "waiting" | "uploading" | "creating" | "done";

interface Item {
  id: number;
  file: File;
  /** why the site would surely refuse it: it is not sent */
  refused: string | null;
  nsfw: boolean;
  /** the viewer changed the box: what the card says no longer sets it */
  nsfwTouched: boolean;
  step: Step;
  /** share of the file sent, 0 to 1 */
  sent: number;
  outcome?: Outcome;
}

/** The tags a file is sent with: the batch's, with the NSFW tag as its box says. */
export function tagsFor(batchTags: string, nsfw: boolean): string[] {
  const names = batchTags
    .split(/\s+/)
    .filter(Boolean)
    .filter((name) => name.toLowerCase() !== NSFW_TAG);
  const unique = names.filter((name, i) => names.indexOf(name) === i);
  return nsfw ? [...unique, NSFW_TAG] : unique;
}

let nextId = 1;

function Progress({ item }: { item: Item }) {
  const label =
    item.step === "waiting"
      ? "Waiting"
      : item.step === "creating"
        ? "Making the post…"
        : `Sending, ${Math.round(item.sent * 100)}%`;
  return (
    <div className="flex min-w-40 flex-1 flex-col gap-1">
      <div
        role="progressbar"
        aria-label={`${item.file.name}: ${label}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(item.sent * 100)}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width]"
          style={{ width: `${item.step === "creating" ? 100 : item.sent * 100}%` }}
        />
      </div>
      <span className="text-muted-foreground text-xs">{label}</span>
    </div>
  );
}

function Result({ outcome, onRetry }: { outcome: Outcome; onRetry(): void }) {
  switch (outcome.kind) {
    case "created": {
      const { post } = outcome;
      const card = post.card;
      return (
        <div className="flex flex-col gap-0.5">
          <span className="font-medium text-ok">
            Created:{" "}
            <Link
              to="/posts/$id"
              params={{ id: String(post.id) }}
              className="text-link underline"
            >
              {card?.name ? card.name : `post ${post.id}`}
            </Link>
          </span>
          {card ? (
            <span className="text-muted-foreground text-xs">
              Card {card.spec?.toUpperCase()}, {card.format?.toUpperCase()},{" "}
              {card.greetingCount ?? 0} greeting{card.greetingCount === 1 ? "" : "s"},{" "}
              {card.lorebookEntryCount
                ? `lorebook of ${card.lorebookEntryCount} entries`
                : "no lorebook"}
            </span>
          ) : null}
        </div>
      );
    }
    case "duplicate":
      return (
        <span className="font-medium text-warn">
          Already on the site:{" "}
          <Link
            to="/posts/$id"
            params={{ id: String(outcome.postId) }}
            className="text-link underline"
          >
            post {outcome.postId}
          </Link>
        </span>
      );
    case "refused":
      return (
        <div className="flex flex-col">
          <span className="font-medium text-destructive">
            Refused: {outcome.error.title}
          </span>
          <span className="text-muted-foreground text-sm">
            {outcome.error.description}
          </span>
        </div>
      );
    case "failed":
    case "cancelled":
      return (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-destructive">
            {outcome.kind === "cancelled"
              ? "Cancelled"
              : `Not sent: ${outcome.error.description}`}
          </span>
          <Button variant="outline" size="sm" onClick={onRetry}>
            <RotateCcw />
            Try again
          </Button>
        </div>
      );
  }
}

/** Where uploading is not for this user: why, and what to do. */
function NotAllowed() {
  const { user } = useAuth();
  const info = useQuery(infoQuery);
  const rank = uploadRank(info.data?.config?.privileges);
  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-3 px-4 py-6 sm:px-8">
      <h1 className="font-semibold font-serif text-3xl">Upload</h1>
      {user === null ? (
        <p>
          Uploading needs an account.{" "}
          <Link
            to="/login"
            search={{ redirect: "/upload" }}
            className="text-link underline"
          >
            Log in
          </Link>{" "}
          to upload.
        </p>
      ) : (
        <p>
          Your account cannot upload on this site
          {rank && rank !== "nobody" ? `: that takes the rank ${rank} or higher` : ""}.
        </p>
      )}
    </main>
  );
}

/**
 * `/upload`: files to post, one or many, with the batch's safety and tags
 * and a NSFW box per file; sent {PARALLEL} at a time, each with its
 * progress, and each with what became of it.
 */
export function UploadPage() {
  const allowed = useCanUpload();
  if (allowed === null) {
    return (
      <main className="mx-auto max-w-[1360px] px-4 py-6 sm:px-8">
        <p className="text-muted-foreground">Loading…</p>
      </main>
    );
  }
  return allowed ? <Uploader /> : <NotAllowed />;
}

function Uploader() {
  const info = useQuery(infoQuery);
  const id = useId();
  const picker = useRef<HTMLInputElement>(null);
  const [safety, setSafety] = useState<Batch["safety"]>("safe");
  const [tags, setTags] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const running = useRef(new Map<number, AbortController>());

  const update = (itemId: number, change: Partial<Item>) =>
    setItems((current) =>
      current.map((item) => (item.id === itemId ? { ...item, ...change } : item)),
    );

  const add = (files: FileList | File[]) => {
    const added: Item[] = [...files].map((file) => ({
      id: nextId++,
      file,
      refused: refusal(file, info.data?.maxUploadSize, info.data?.acceptedTypes),
      nsfw: false,
      nsfwTouched: false,
      step: "ready",
      sent: 0,
    }));
    setItems((current) => [...current, ...added]);
    for (const item of added) {
      if (item.refused) {
        continue;
      }
      // what the card itself says, unless the viewer said otherwise first
      cardSaysNsfw(item.file).then((nsfw) => {
        if (nsfw) {
          setItems((current) =>
            current.map((one) =>
              one.id === item.id && !one.nsfwTouched ? { ...one, nsfw: true } : one,
            ),
          );
        }
      });
    }
  };

  const busy = items.some((item) =>
    ["waiting", "uploading", "creating"].includes(item.step),
  );
  const started = items.some((item) => item.step !== "ready");

  // leaving while files are on their way asks first (in the app, and the tab)
  useBlocker({
    shouldBlockFn: () =>
      !window.confirm("Files are still being uploaded. Leave and stop them?"),
    enableBeforeUnload: () => busy,
    disabled: !busy,
  });

  // the next waiting files, {PARALLEL} at a time
  // biome-ignore lint/correctness/useExhaustiveDependencies: started from the items' steps
  useEffect(() => {
    const active = items.filter(
      (item) => item.step === "uploading" || item.step === "creating",
    );
    const waiting = items.filter((item) => item.step === "waiting");
    for (const item of waiting.slice(0, Math.max(0, PARALLEL - active.length))) {
      if (running.current.has(item.id)) {
        continue;
      }
      const controller = new AbortController();
      running.current.set(item.id, controller);
      update(item.id, { step: "uploading", sent: 0 });
      send(
        item.file,
        { safety, tags: tagsFor(tags, item.nsfw) },
        {
          signal: controller.signal,
          onProgress: (sent) => update(item.id, { sent }),
          onCreating: () => update(item.id, { step: "creating", sent: 1 }),
        },
      ).then((outcome) => {
        running.current.delete(item.id);
        update(item.id, { step: "done", outcome });
      });
    }
  }, [items]);

  // nothing goes on in the background once the page is gone
  useEffect(() => {
    const controllers = running.current;
    return () => {
      for (const controller of controllers.values()) {
        controller.abort();
      }
    };
  }, []);

  const startAll = () =>
    setItems((current) =>
      current.map((item) =>
        item.step === "ready" && !item.refused ? { ...item, step: "waiting" } : item,
      ),
    );

  const cancel = (item: Item) => {
    const controller = running.current.get(item.id);
    if (controller) {
      controller.abort();
    } else if (item.step === "waiting") {
      update(item.id, { step: "done", outcome: { kind: "cancelled" } });
    }
  };

  const cancelRest = () => {
    for (const item of items) {
      cancel(item);
    }
  };

  const retry = (item: Item) =>
    update(item.id, { step: "waiting", sent: 0, outcome: undefined });

  const remove = (item: Item) =>
    setItems((current) => current.filter((one) => one.id !== item.id));

  const drop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer.files.length) {
      add(event.dataTransfer.files);
    }
  };

  const sendable = items.filter((item) => item.step === "ready" && !item.refused);

  return (
    <main className="mx-auto flex max-w-[1360px] flex-col gap-5 px-4 py-6 sm:px-8">
      <h1 className="font-semibold font-serif text-3xl">Upload</h1>

      <section
        aria-label="Files"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={cn(
          "flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed bg-card px-6 py-10 text-center",
          dragging ? "border-primary bg-accent" : "border-control-border",
        )}
      >
        <FileUp aria-hidden className="size-8 text-muted-foreground" />
        <p>
          Drop pictures, videos and character cards here (PNG or CHARX), one or many.
        </p>
        <Button variant="outline" onClick={() => picker.current?.click()}>
          Choose files
        </Button>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          data-testid="file-picker"
          onChange={(event) => {
            if (event.target.files) {
              add(event.target.files);
            }
            event.target.value = "";
          }}
        />
      </section>

      <section
        aria-label="For every file"
        className="flex flex-col gap-4 rounded-2xl border bg-card p-4 sm:flex-row sm:items-start sm:gap-8"
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 font-semibold text-sm">Safety</legend>
          <RadioGroup
            value={safety}
            onValueChange={(value) => setSafety(value as Batch["safety"])}
            className="flex gap-4"
            disabled={busy}
          >
            {SAFETIES.map((one) => (
              <div key={one} className="flex items-center gap-2">
                <RadioGroupItem id={`${id}-${one}`} value={one} />
                <Label htmlFor={`${id}-${one}`} className="font-normal">
                  {SAFETY_LABELS[one]}
                </Label>
              </div>
            ))}
          </RadioGroup>
        </fieldset>
        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <label htmlFor={`${id}-tags`} className="font-semibold text-sm">
            Tags{" "}
            <span className="font-normal text-muted-foreground">
              (optional, separated by spaces)
            </span>
          </label>
          <CompletionInput
            id={`${id}-tags`}
            mode="names"
            value={tags}
            onChange={setTags}
            placeholder="e.g. fantasy slow_burn"
            inputClassName="h-11"
          />
        </div>
      </section>

      {items.length ? (
        <section
          aria-label="Upload list"
          className="flex flex-col rounded-2xl border bg-card"
        >
          <ul className="divide-y">
            {items.map((item) => (
              <li
                key={item.id}
                aria-label={item.file.name}
                className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3"
              >
                <div className="flex min-w-48 flex-[2_1_16rem] flex-col">
                  <span className="truncate font-medium">{item.file.name}</span>
                  <span className="text-muted-foreground text-xs">
                    {formatBytes(item.file.size)}
                  </span>
                </div>
                {item.refused ? (
                  <span className="flex-[3_1_20rem] text-destructive text-sm">
                    Not sent: {item.refused}
                  </span>
                ) : (
                  <>
                    <div className="flex items-center gap-2">
                      <Checkbox
                        id={`${id}-nsfw-${item.id}`}
                        checked={item.nsfw}
                        disabled={item.step !== "ready"}
                        onCheckedChange={(checked) =>
                          update(item.id, { nsfw: checked === true, nsfwTouched: true })
                        }
                      />
                      <Label htmlFor={`${id}-nsfw-${item.id}`} className="font-normal">
                        NSFW
                      </Label>
                    </div>
                    <div className="flex flex-[3_1_20rem] items-center gap-3">
                      {item.step === "done" && item.outcome ? (
                        <Result outcome={item.outcome} onRetry={() => retry(item)} />
                      ) : item.step === "ready" ? (
                        <span className="text-muted-foreground text-sm">Ready</span>
                      ) : (
                        <Progress item={item} />
                      )}
                    </div>
                  </>
                )}
                {item.step === "ready" ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${item.file.name}`}
                    onClick={() => remove(item)}
                  >
                    <X />
                  </Button>
                ) : item.step !== "done" ? (
                  <Button variant="outline" size="sm" onClick={() => cancel(item)}>
                    Cancel
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3 border-t px-4 py-3">
            {sendable.length ? (
              <Button onClick={startAll}>
                Upload {sendable.length} file{sendable.length === 1 ? "" : "s"}
              </Button>
            ) : null}
            {busy ? (
              <Button variant="outline" onClick={cancelRest}>
                Cancel the rest
              </Button>
            ) : null}
            {started && !busy ? (
              <Button variant="outline" onClick={() => setItems([])}>
                Upload more
              </Button>
            ) : null}
            <span className="text-muted-foreground text-sm">
              Checked NSFW adds the tag {NSFW_TAG}; a card whose own tags say NSFW gets
              it from the site in any case.
            </span>
          </div>
        </section>
      ) : null}
      {info.isError ? <ApiErrorMessage error={info.error} /> : null}
    </main>
  );
}
