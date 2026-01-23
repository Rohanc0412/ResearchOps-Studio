import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";

import "./index.css";
import { AuthProvider } from "./auth/AuthProvider";
import { queryClient } from "./api/queryClient";
import { router } from "./routes/router";
import { RootErrorBoundary } from "./components/ui/RootErrorBoundary";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RootErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </QueryClientProvider>
    </RootErrorBoundary>
  </React.StrictMode>
);

