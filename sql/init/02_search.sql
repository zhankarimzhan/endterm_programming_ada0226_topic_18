-- Поиск похожих вопросов средствами PostgreSQL: сходство по триграммам символов (pg_trgm).
-- Устойчив к опечаткам и разным написаниям («аиту» / «AITU»).

CREATE EXTENSION IF NOT EXISTS pg_trgm;

INSERT INTO methods (name, preprocessing) VALUES ('pg_trgm', 'lower')
ON CONFLICT (name, preprocessing) DO NOTHING;
