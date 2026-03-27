function titleCase(value: string): string {
  if (!value) return value;
  return value.replace(/(^|[_-])([a-z])/g, (_, _sep, ch) => ` ${ch.toUpperCase()}`).trim();
}

export function deriveRunUpdate(event: {
  stage?: string;
  message?: string;
  payload?: Record<string, unknown>;
}) {
  const payload = event.payload ?? {};
  const rawStatus = payload["status"] ?? payload["to_status"];
  const status = typeof rawStatus === "string" ? rawStatus : null;

  let primaryText = "Working";
  let secondaryText: string | undefined;

  if (event.message?.startsWith("Starting stage:")) {
    primaryText = `Working on ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.message?.startsWith("Finished stage:")) {
    primaryText = `Finished ${titleCase(event.stage ?? "")}`.trim();
  } else if (event.stage) {
    primaryText = `Processing ${titleCase(event.stage)}`;
  } else if (event.message) {
    primaryText = event.message;
  }

  const step = payload["step"];
  if (typeof step === "string" && step.trim()) {
    secondaryText = `Step: ${step}`;
  } else {
    const artifactType = payload["artifact_type"];
    if (typeof artifactType === "string" && artifactType.trim()) {
      secondaryText = `Artifact: ${artifactType}`;
    }
  }

  return { status, primaryText, secondaryText };
}
