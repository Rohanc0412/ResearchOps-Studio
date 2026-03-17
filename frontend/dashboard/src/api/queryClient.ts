import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        if (error instanceof Error && error.name === "ApiError") return true;
        return false;
      },
      retryDelay: (attemptIndex) => Math.min(2000, 500 * 2 ** attemptIndex)
    },
    mutations: {
      retry: 0
    }
  }
});

