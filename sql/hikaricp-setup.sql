-- Run this same script once in EACH database: hikaricp-1, hikaricp-2, hikaricp-3
-- (pgAdmin: right-click the database -> Query Tool -> paste -> Execute).
-- dbname defaults to current_database(), so every row records which DB it lives in
-- without editing the script per database.

CREATE TABLE IF NOT EXISTS employees (
    id         SERIAL       PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    email      VARCHAR(150) NOT NULL UNIQUE,
    department VARCHAR(50),
    dbname     VARCHAR(50)  NOT NULL DEFAULT current_database(),
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO employees (name, email, department) VALUES
    ('Alice ' || current_database(), 'alice@' || current_database() || '.local', 'Engineering'),
    ('Bob '   || current_database(), 'bob@'   || current_database() || '.local', 'Sales'),
    ('Carol ' || current_database(), 'carol@' || current_database() || '.local', 'HR')
ON CONFLICT (email) DO NOTHING;

SELECT * FROM employees;
