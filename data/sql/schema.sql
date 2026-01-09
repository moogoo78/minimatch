-- Enable foreign key constraints (SQLite usually has this off by default)
PRAGMA foreign_keys = ON;

CREATE TABLE dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE taxa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    authors TEXT,
    year INTEGER,
    rank_id INTEGER,
    status_id INTEGER,
    dataset_id INTEGER NOT NULL,
    source_id TEXT,
    catalog_number TEXT,
    link TEXT,
    source_data TEXT,

    FOREIGN KEY (dataset_id) REFERENCES dataset(id) ON DELETE CASCADE,
    FOREIGN KEY (rank_id) REFERENCES taxa_rank(id) ON DELETE CASCADE
);

-- status_id: 1: accepted, 2:not-accepted, (synonyms?)
--

CREATE TABLE taxa_common_name (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taxa_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    lang TEXT NOT NULL,
    sort INTEGER,

    FOREIGN KEY (taxa_id) REFERENCES taxa(id) ON DELETE CASCADE
);

CREATE TABLE taxa_rank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort INTEGER
);

CREATE TABLE taxa_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE taxa_closure (
    ancestor_id INTEGER NOT NULL,
    descendant_id INTEGER NOT NULL,
    depth INTEGER NOT NULL,

    PRIMARY KEY (ancestor_id, descendant_id),

    FOREIGN KEY (ancestor_id) REFERENCES taxa(id) ON DELETE CASCADE,
    FOREIGN KEY (descendant_id) REFERENCES taxa(id) ON DELETE CASCADE
);

-- Index for faster lookups when searching "up" the tree (finding parents)
CREATE INDEX idx_closure_descendant ON taxa_closure(descendant_id);
