import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        // Don't retry client errors (4xx) — they are deterministic
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
        // Retry once for network failures and server errors (5xx)
        return true;
      },
      retryDelay: (attemptIndex) => Math.min(2000, 500 * 2 ** attemptIndex)
    },
    mutations: {
      retry: 0
    }
  }
});

