-- Схема Nanotasks для DuckDB.
-- В DuckDB нет AUTOINCREMENT — используем последовательности (SEQUENCE).
-- FK-ограничения намеренно не объявляем (целостность держим в репозитории),
-- чтобы схема легко переносилась на другой встроенный движок.

CREATE SEQUENCE IF NOT EXISTS seq_projects START 1;
CREATE SEQUENCE IF NOT EXISTS seq_tasks START 1;
CREATE SEQUENCE IF NOT EXISTS seq_prompts START 1;
CREATE SEQUENCE IF NOT EXISTS seq_artifacts START 1;
CREATE SEQUENCE IF NOT EXISTS seq_events START 1;

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_projects'),
    name        VARCHAR NOT NULL,
    description VARCHAR DEFAULT '',
    language    VARCHAR DEFAULT 'python',
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_tasks'),
    project_id  INTEGER NOT NULL,
    parent_id   INTEGER,
    key         VARCHAR NOT NULL,
    title       VARCHAR NOT NULL,
    type        VARCHAR NOT NULL DEFAULT 'code',
    body        VARCHAR DEFAULT '',
    file_path   VARCHAR,
    depends_on  VARCHAR DEFAULT '[]',   -- JSON-массив ключей задач-зависимостей
    order_idx   INTEGER DEFAULT 0,
    status      VARCHAR NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS prompts (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_prompts'),
    task_id     INTEGER NOT NULL,
    role        VARCHAR NOT NULL,       -- 'prompt_builder' и т.п.
    model       VARCHAR,
    content     VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_artifacts'),
    task_id     INTEGER NOT NULL,
    prompt_id   INTEGER,
    model       VARCHAR,
    content     VARCHAR NOT NULL,
    file_path   VARCHAR,
    version     INTEGER DEFAULT 1,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY DEFAULT nextval('seq_events'),
    project_id  INTEGER,
    task_id     INTEGER,
    level       VARCHAR DEFAULT 'info',
    message     VARCHAR NOT NULL,
    created_at  TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_id);
CREATE INDEX IF NOT EXISTS idx_prompts_task ON prompts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
