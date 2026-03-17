-- 0001: tenant enforcement + audit logs

-- Ensure artifacts has tenant_id (backfilled from runs)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='artifacts' AND column_name='tenant_id'
  ) THEN
    ALTER TABLE artifacts ADD COLUMN tenant_id TEXT;
    UPDATE artifacts a
      SET tenant_id = r.tenant_id
      FROM runs r
      WHERE a.run_id = r.id AND a.tenant_id IS NULL;
    ALTER TABLE artifacts ALTER COLUMN tenant_id SET NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_artifacts_tenant_id ON artifacts (tenant_id);
    CREATE INDEX IF NOT EXISTS idx_artifacts_tenant_run ON artifacts (tenant_id, run_id);
  END IF;
END $$;

-- Audit logs table
CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  actor_user_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NULL,
  metadata JSONB NOT NULL,
  ip TEXT NULL,
  user_agent TEXT NULL,
  request_id TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant ON audit_logs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at);

-- Hot table composite indexes
CREATE INDEX IF NOT EXISTS idx_runs_tenant_id ON runs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_runs_tenant_run ON runs (tenant_id, id);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_id ON jobs (tenant_id);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_run ON jobs (tenant_id, run_id);

