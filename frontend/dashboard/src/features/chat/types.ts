export type ReportSectionContent = {
  text: string;
  citations?: number[];
  isBullet?: boolean;
};

export type ReportSection = {
  id: string;
  heading: string;
  content: ReportSectionContent[];
};

export type Report = {
  title: string;
  sections: ReportSection[];
};

export type ActiveRunStatus = "running" | "failed" | "succeeded" | "canceled";

export type ActiveRun = {
  runId: string;
  status: ActiveRunStatus;
  question?: string;
  primaryText: string;
  secondaryText?: string;
  startedAt: string;
  error?: string;
};
