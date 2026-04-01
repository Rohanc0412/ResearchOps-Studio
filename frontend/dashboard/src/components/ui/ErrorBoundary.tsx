import React from "react";
import { ErrorBanner } from "./ErrorBanner";

type Props = {
  children: React.ReactNode;
  fallback?: React.ReactNode;
};

type State = { error: Error | null };

export class ErrorBoundary extends React.Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override render() {
    if (this.state.error) {
      if (this.props.fallback !== undefined) {
        return this.props.fallback;
      }
      return (
        <div className="flex h-full items-center justify-center p-6">
          <ErrorBanner message={this.state.error.message} />
        </div>
      );
    }
    return this.props.children;
  }
}
