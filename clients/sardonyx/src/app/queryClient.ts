import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/errors";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // asking again does not help with a refusal: only with a site that
      // could not be reached, or that failed itself
      retry: (failures, error) =>
        failures < 2 &&
        (!(error instanceof ApiError) || error.status === 0 || error.status >= 500),
    },
  },
});
