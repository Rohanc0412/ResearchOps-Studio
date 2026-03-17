import React from "react";
import { ErrorBanner } from "./ErrorBanner";

type State = { error: Error | null };

export class RootErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="mx-auto flex min-h-screen max-w-2xl items-center p-6">
          <ErrorBanner message={this.state.error.message} />
        </div>
      );
    }
    return this.props.children;
  }
}
