DO
$$
BEGIN
    IF NOT EXISTS (
        SELECT FROM pg_catalog.pg_roles WHERE rolname = 'langfuse'
    ) THEN
        CREATE ROLE langfuse WITH LOGIN PASSWORD 'langfuse';
    END IF;
END
$$;

\set langfuse_db 'langfuse'

SELECT 'CREATE DATABASE ' || :'langfuse_db' || ' OWNER langfuse'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = :'langfuse_db'
);
\gexec

GRANT ALL PRIVILEGES ON DATABASE langfuse TO langfuse;
