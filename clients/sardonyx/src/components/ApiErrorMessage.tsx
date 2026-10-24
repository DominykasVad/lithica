import { CircleAlert } from "lucide-react";
import { asApiError } from "@/api/errors";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Any failure, the way the app shows every failure: the API's title and its
 * description, as plain text.
 */
export function ApiErrorMessage({ error }: { error: unknown }) {
  const { title, description } = asApiError(error);
  return (
    <Alert variant="destructive" role="alert">
      <CircleAlert aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{description}</AlertDescription>
    </Alert>
  );
}
