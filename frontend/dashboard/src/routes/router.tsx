import { createBrowserRouter, Navigate } from "react-router-dom";

import { ProtectedRoute } from "../auth/ProtectedRoute";
import { AppLayout } from "../components/layout/AppLayout";
import { ArtifactsPage } from "../pages/ArtifactsPage";
import { ChatViewPage } from "../pages/ChatViewPage";
import { ErrorPage } from "../pages/ErrorPage";
import { EvidencePage } from "../pages/EvidencePage";
import { LoginPage } from "../pages/LoginPage";
import { ProjectDetailPage } from "../pages/ProjectDetailPage";
import { ProjectsPage } from "../pages/ProjectsPage";
import { RunViewerPage } from "../pages/RunViewerPage";
import { SecurityPage } from "../pages/SecurityPage";

export const router = createBrowserRouter([
  {
    errorElement: <ErrorPage />,
    children: [
      { path: "/", element: <Navigate to="/projects" replace /> },
      { path: "/login", element: <LoginPage /> },
      {
        element: <ProtectedRoute />,
        children: [
          {
            element: <AppLayout />,
            children: [
              { path: "/projects", element: <ProjectsPage /> },
              { path: "/projects/:projectId", element: <ProjectDetailPage /> },
              { path: "/projects/:projectId/chats/:chatId", element: <ChatViewPage /> },
              { path: "/runs/:runId", element: <RunViewerPage /> },
              { path: "/runs/:runId/artifacts", element: <ArtifactsPage /> },
              { path: "/evidence/snippets/:snippetId", element: <EvidencePage /> },
              { path: "/security", element: <SecurityPage /> }
            ]
          }
        ]
      }
    ]
  }
]);

