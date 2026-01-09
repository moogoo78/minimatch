-- create-index.sql
-- Performance optimization indexes for minitaxa.db
--
-- This script creates indexes to speed up minimatch.py queries by 2-5x.
-- Run once after creating/updating the database.
--
-- Usage:
--   sqlite3 minitaxa.db < data/sql/create-index.sql
--
-- Or from within sqlite3:
--   .read data/sql/create-index.sql

-- ============================================================================
-- Indexes for taxa table lookups
-- ============================================================================

-- Index for finding species by name and dataset (used in main query)
-- Speeds up: WHERE t.name = ? AND t.dataset_id = 1
CREATE INDEX IF NOT EXISTS idx_taxa_name_dataset
    ON taxa(name, dataset_id);

-- Index for rank-based filtering
-- Speeds up: JOIN taxa_rank r ON t.rank_id = r.id WHERE t.dataset_id = ?
CREATE INDEX IF NOT EXISTS idx_taxa_rank
    ON taxa(rank_id, dataset_id);

-- Index for Chinese name matching (composite key)
-- Speeds up: WHERE t.name = ? AND t.rank_id = ? AND t.dataset_id = 2
CREATE INDEX IF NOT EXISTS idx_taxa_name_rank_dataset
    ON taxa(name, rank_id, dataset_id);

-- ============================================================================
-- Indexes for taxa_closure table (hierarchy queries)
-- ============================================================================

-- Index for finding ancestors of a descendant
-- Speeds up: WHERE c.descendant_id = ? ORDER BY c.depth DESC
CREATE INDEX IF NOT EXISTS idx_closure_descendant
    ON taxa_closure(descendant_id, depth);

-- Index for finding descendants of an ancestor
-- Speeds up: WHERE c.ancestor_id = ?
CREATE INDEX IF NOT EXISTS idx_closure_ancestor
    ON taxa_closure(ancestor_id);

-- ============================================================================
-- Indexes for taxa_common_name table
-- ============================================================================

-- Index for retrieving common names by language
-- Speeds up: WHERE taxa_id = ? AND lang = 'zh'
CREATE INDEX IF NOT EXISTS idx_common_name_lang
    ON taxa_common_name(taxa_id, lang);

-- ============================================================================
-- Analyze tables for query optimizer
-- ============================================================================

-- Update statistics for the query planner
-- This helps SQLite choose the most efficient query plans
ANALYZE;

-- ============================================================================
-- Verification queries
-- ============================================================================

-- To verify indexes were created, run:
-- SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%';

-- Expected output:
-- idx_taxa_name_dataset|taxa
-- idx_taxa_rank|taxa
-- idx_taxa_name_rank_dataset|taxa
-- idx_closure_descendant|taxa_closure
-- idx_closure_ancestor|taxa_closure
-- idx_common_name_lang|taxa_common_name
