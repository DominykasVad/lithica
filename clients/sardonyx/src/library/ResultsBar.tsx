import { Link } from "@tanstack/react-router";
import { ApiErrorMessage } from "@/components/ApiErrorMessage";
import { Button } from "@/components/ui/button";
import { PER_PAGE_CHOICES, type PerPage } from "./perPage";

const LABELS: Record<string, string> = { 50: "50", 100: "100", auto: "Auto load" };

/** How many results there are, and the choice of how to list them. */
export function ResultsBar({
  total,
  perPage,
  onPerPage,
}: {
  total: number | null;
  perPage: PerPage;
  onPerPage(next: PerPage): void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <p className="text-muted-foreground" aria-live="polite">
        {total === null ? (
          "Searching…"
        ) : (
          <>
            <strong className="text-foreground">{total}</strong>{" "}
            {total === 1 ? "result" : "results"}
          </>
        )}
      </p>
      <label className="ml-auto flex items-center gap-2 text-sm">
        Per page
        <select
          value={String(perPage)}
          onChange={(event) => {
            const value = event.target.value;
            onPerPage(value === "auto" ? "auto" : (Number(value) as PerPage));
          }}
          className="h-9 rounded-md border border-control-border bg-card px-2 text-foreground"
        >
          {PER_PAGE_CHOICES.map((choice) => (
            <option key={choice} value={String(choice)}>
              {LABELS[String(choice)]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

export function NoResults({ q }: { q: string }) {
  return (
    <p className="py-12 text-center text-muted-foreground">
      {q ? (
        <>
          Nothing found for <code className="font-mono text-foreground">{q}</code>.
        </>
      ) : (
        "There are no posts yet."
      )}
    </p>
  );
}

export function PastTheEnd({ q }: { q: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
      <p>This page is past the end of the results.</p>
      <Link
        to="/posts"
        search={{ q: q || undefined }}
        className="text-link underline-offset-4 hover:underline"
      >
        Go to the first page
      </Link>
    </div>
  );
}

/** A failure, and a way to try again. */
export function Failed({ error, onRetry }: { error: unknown; onRetry(): void }) {
  return (
    <div className="flex flex-col items-start gap-2">
      <ApiErrorMessage error={error} />
      <Button variant="outline" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
