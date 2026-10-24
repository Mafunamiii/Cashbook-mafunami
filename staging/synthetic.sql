-- This fixture exists only in the disposable staging PostgreSQL volume.
CREATE TABLE staging_fixture (label text PRIMARY KEY);
INSERT INTO staging_fixture (label) VALUES ('synthetic-only');
