-- Runs once on an empty data dir. The Control Plane's Flyway migrations own all
-- application schema; pgcrypto provides digest()/crypt() used by a few of them.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
