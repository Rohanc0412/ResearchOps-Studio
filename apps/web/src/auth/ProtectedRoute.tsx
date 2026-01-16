import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "./useAuth";
import { Spinner } from "../components/ui/Spinner";

export function ProtectedRoute() {
  const auth = useAuth();
  const location = useLocation();

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="Loading session…" />
      </div>
    );
  }

  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <Outlet />;
}

