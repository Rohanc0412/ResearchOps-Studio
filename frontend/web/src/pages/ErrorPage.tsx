import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { ErrorBanner } from "../components/ui/ErrorBanner";

export function ErrorPage() {
  const error = useRouteError();

  if (isRouteErrorResponse(error)) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <ErrorBanner title={`Error ${error.status}`} message={error.statusText} />
      </div>
    );
  }

  const message = error instanceof Error ? error.message : "Unknown error";
  return (
    <div className="mx-auto max-w-2xl p-6">
      <ErrorBanner message={message} />
    </div>
  );
}

