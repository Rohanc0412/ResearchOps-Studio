SELECT 'CREATE DATABASE researchops_test'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'researchops_test'
)
\gexec
