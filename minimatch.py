#!/usr/bin/env python3
"""
minimatch.py - Local taxonomy reconciliation using minitaxa.db

The local SQLite database is always matched first; names it cannot resolve fall
through to the fallback backend selected with --source:
  local        No fallback (local only, default).
               Local matching uses mycobank (dataset_id=1) for higher taxa via
               the closure table and taicol (dataset_id=6) for Chinese names.
  globalnames  Fall back to the Global Names Verifier API
               (https://verifier.globalnames.org) for local misses. --gn-source
               selects the GN data source id(s) (e.g. 1=Catalogue of Life,
               11=GBIF, 12=EOL). No Chinese names from this source.

Usage: minimatch.py input.csv output.csv [--source local|globalnames]
                    [--dataset-id IDS] [--gn-source IDS] [--db DB_PATH] [--stats] [-v]
"""

import argparse
import sys
import csv
import json
import logging
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional, List


# Rank mapping for output fields
RANK_TO_FIELD = {
    'Kingdom': 'kingdom_name',
    'Phylum': 'phylum_name',
    'Division': 'phylum_name',  # Division is synonym for Phylum in some systems
    'Class': 'class_name',
    'Order': 'order_name',
    'Family': 'family_name',
    'Genus': 'genus_name',
}

RANK_TO_FIELD_ZH = {
    'Kingdom': 'kingdom_name_zh',
    'Phylum': 'phylum_name_zh',
    'Division': 'phylum_name_zh',
    'Class': 'class_name_zh',
    'Order': 'order_name_zh',
    'Family': 'family_name_zh',
    'Genus': 'genus_name_zh',
}

# Ranks to query (in order of hierarchy)
TARGET_RANKS = ['Kingdom', 'Phylum', 'Division', 'Class', 'Order', 'Family', 'Genus']

# TaiCOL dataset providing Chinese common names for higher taxa. Bump this when
# importing a newer TaiCOL version (see data/loaders/import-taicol.py).
TAICOL_DATASET_ID = 6

# Some datasets (e.g. taicol) have no closure hierarchy; instead each taxon row
# carries its full lineage as flat keys in the source_data JSON. Map those keys
# to output fields. The Chinese name uses the same key with a '_c' suffix.
SOURCE_DATA_RANK_TO_FIELD = {
    'kingdom': ('kingdom_name', 'kingdom_name_zh'),
    'phylum': ('phylum_name', 'phylum_name_zh'),
    'class': ('class_name', 'class_name_zh'),
    'order': ('order_name', 'order_name_zh'),
    'family': ('family_name', 'family_name_zh'),
    'genus': ('genus_name', 'genus_name_zh'),
}


class MinimatchDB:
    """Database handler for local taxonomy matching"""

    def __init__(self, db_path: str = 'minitaxa.db',
                 dataset_ids: Optional[List[int]] = None):
        self.db_path = db_path
        # Datasets to match against, in priority order (first match wins)
        self.dataset_ids = dataset_ids if dataset_ids else [1]
        self.conn = None
        self.cursor = None

    def connect(self):
        """Connect to database with optimizations"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # SQLite performance optimizations
        self.cursor.execute("PRAGMA cache_size = -64000")  # 64MB cache
        self.cursor.execute("PRAGMA temp_store = MEMORY")  # Use memory for temp tables
        self.cursor.execute("PRAGMA mmap_size = 268435456")  # 256MB memory-mapped I/O
        self.cursor.execute("PRAGMA journal_mode = WAL")  # Write-Ahead Logging for better concurrency

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def get_higher_taxa(self, scientific_name: str) -> Optional[Dict[str, str]]:
        """
        Get higher taxa for a scientific name.

        Tries each configured dataset in priority order and returns the
        first dataset that yields a match.

        Args:
            scientific_name: Species scientific name to look up

        Returns:
            Dictionary with taxonomy fields or None if not found in any dataset
        """
        # Trim leading/trailing whitespace so padded input names still match.
        scientific_name = scientific_name.strip() if scientific_name else scientific_name
        if not scientific_name:
            return None

        for dataset_id in self.dataset_ids:
            result = self._query_dataset(scientific_name, dataset_id)
            if result:
                return result
        return None

    def _query_dataset(self, scientific_name: str,
                       dataset_id: int) -> Optional[Dict[str, str]]:
        """
        Look up higher taxa for a scientific name within a single dataset.

        Primary path: a single query walks the taxa_closure hierarchy to get
        all ancestors with their Chinese names (datasets like mycobank/fishdb/
        nmmba). If the dataset has no closure hierarchy (e.g. taicol), falls
        back to reading the lineage from the taxon's source_data JSON.

        Args:
            scientific_name: Species scientific name to look up
            dataset_id: Dataset to match the species and higher taxa against

        Returns:
            Dictionary with taxonomy fields or None if not found
        """
        # Single optimized query to get all ancestors with Chinese names and dataset info
        self.cursor.execute("""
            WITH species AS (
                SELECT id, dataset_id
                FROM taxa
                WHERE name = ? AND dataset_id = ?
                LIMIT 1
            ),
            ancestor_taxa AS (
                SELECT DISTINCT
                    t.id,
                    t.name as taxa_name,
                    r.name as rank,
                    c.depth,
                    d.name as dataset_name,
                    d.version as dataset_version
                FROM taxa t
                JOIN taxa_closure c ON t.id = c.ancestor_id
                JOIN taxa_rank r ON t.rank_id = r.id
                JOIN species s ON c.descendant_id = s.id
                LEFT JOIN dataset d ON d.id = s.dataset_id
                WHERE t.dataset_id = ?
            )
            SELECT
                at.taxa_name,
                at.rank,
                tcn.name as chinese_name,
                at.dataset_name,
                at.dataset_version
            FROM ancestor_taxa at
            LEFT JOIN taxa_rank r ON r.name = at.rank
            LEFT JOIN taxa_rank r2 ON (
                -- Handle Division/Phylum synonym: allow matching either
                r2.id = r.id
                OR (at.rank IN ('Division', 'Phylum') AND r2.name IN ('Division', 'Phylum'))
            )
            LEFT JOIN taxa t2 ON (
                t2.name = at.taxa_name
                AND t2.rank_id = r2.id
                AND t2.dataset_id = ?
            )
            LEFT JOIN taxa_common_name tcn ON (
                tcn.taxa_id = t2.id
                AND tcn.lang = 'zh'
            )
            GROUP BY at.taxa_name, at.rank, at.depth, at.dataset_name, at.dataset_version
            ORDER BY at.depth DESC
        """, (scientific_name, dataset_id, dataset_id, TAICOL_DATASET_ID))

        ancestors = self.cursor.fetchall()

        if not ancestors:
            # No closure hierarchy for this dataset: try source_data JSON lineage
            return self._lineage_from_source_data(scientific_name, dataset_id)

        result = {}
        dataset_name = None
        dataset_version = None

        # Process all results from single query
        for ancestor in ancestors:
            rank = ancestor['rank']
            taxa_name = ancestor['taxa_name']
            chinese_name = ancestor['chinese_name']

            # Capture dataset info from first row
            if dataset_name is None:
                dataset_name = ancestor['dataset_name']
                dataset_version = ancestor['dataset_version']

            if rank in TARGET_RANKS:
                # Add scientific name
                field_key = RANK_TO_FIELD.get(rank)
                if field_key:
                    result[field_key] = taxa_name

                # Add Chinese name if available
                if chinese_name:
                    field_key_zh = RANK_TO_FIELD_ZH.get(rank)
                    if field_key_zh:
                        result[field_key_zh] = chinese_name

        # Add according_to field with dataset information
        if dataset_name:
            according_to = dataset_name
            if dataset_version:
                according_to += f" (version {dataset_version})"
            result['according_to'] = according_to

        return result if result else None

    def _lineage_from_source_data(self, scientific_name: str,
                                  dataset_id: int) -> Optional[Dict[str, str]]:
        """
        Build higher taxa from a taxon's source_data JSON.

        Used for datasets that store the full lineage as flat keys on each
        taxon row (e.g. taicol: kingdom/phylum/.../genus plus '_c' Chinese
        names) instead of in the taxa_closure table.

        Args:
            scientific_name: Species scientific name to look up
            dataset_id: Dataset to match against

        Returns:
            Dictionary with taxonomy fields or None if not found
        """
        self.cursor.execute("""
            SELECT t.source_data, d.name AS dataset_name, d.version AS dataset_version
            FROM taxa t
            LEFT JOIN dataset d ON d.id = t.dataset_id
            WHERE t.name = ? AND t.dataset_id = ?
            LIMIT 1
        """, (scientific_name, dataset_id))

        row = self.cursor.fetchone()
        if not row or not row['source_data']:
            return None

        try:
            data = json.loads(row['source_data'])
        except (ValueError, TypeError):
            return None

        result = {}
        for json_key, (field_key, field_key_zh) in SOURCE_DATA_RANK_TO_FIELD.items():
            name = data.get(json_key)
            if name:
                result[field_key] = name
            name_zh = data.get(f'{json_key}_c')
            if name_zh:
                result[field_key_zh] = name_zh

        if not result:
            return None

        # Add according_to field with dataset information
        if row['dataset_name']:
            according_to = row['dataset_name']
            if row['dataset_version']:
                according_to += f" (version {row['dataset_version']})"
            result['according_to'] = according_to

        return result


# Global Names Verifier API endpoint (verifications by name).
GN_VERIFIER_URL = 'https://verifier.globalnames.org/api/v1/verifications/'

# Global Names classification rank (lowercase) -> output field.
GN_RANK_TO_FIELD = {
    'kingdom': 'kingdom_name',
    'phylum': 'phylum_name',
    'division': 'phylum_name',  # Division ↔ Phylum synonym
    'class': 'class_name',
    'order': 'order_name',
    'family': 'family_name',
    'genus': 'genus_name',
}


class GlobalNamesVerifier:
    """
    Higher-taxa lookup backed by the Global Names Verifier API.

    Exposes the same get_higher_taxa(name) interface and context-manager
    protocol as MinimatchDB, so it is a drop-in matching backend. The
    dataset_ids are Global Names *data source* ids (e.g. 1=Catalogue of Life,
    11=GBIF); the API restricts verification to those sources.
    """

    def __init__(self, dataset_ids: Optional[List[int]] = None,
                 timeout: int = 30):
        # GN data source ids to restrict to (empty = let GN pick best source).
        self.dataset_ids = dataset_ids if dataset_ids else []
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def get_higher_taxa(self, scientific_name: str) -> Optional[Dict[str, str]]:
        """
        Look up higher taxa for a scientific name via Global Names Verifier.

        Returns a dict with kingdom_name..genus_name and according_to, matching
        the local backend's shape (no Chinese names), or None if unmatched / on
        a request error.
        """
        # Trim leading/trailing whitespace so padded input names still match.
        scientific_name = scientific_name.strip() if scientific_name else scientific_name
        if not scientific_name:
            return None

        params = {'capitalize': 'true'}
        if self.dataset_ids:
            params['data_sources'] = ','.join(str(i) for i in self.dataset_ids)
        url = (GN_VERIFIER_URL + urllib.parse.quote(scientific_name)
               + '?' + urllib.parse.urlencode(params))

        try:
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            logging.getLogger(__name__).warning(
                f"  Global Names request failed for '{scientific_name}': {e}")
            return None

        names = data.get('names') or []
        best = names[0].get('bestResult') if names else None
        if not best:
            return None

        path = best.get('classificationPath') or ''
        ranks = best.get('classificationRanks') or ''
        if not path or not ranks:
            return None

        result = {}
        for taxon_name, rank in zip(path.split('|'), ranks.split('|')):
            field = GN_RANK_TO_FIELD.get(rank.strip().lower())
            if field and taxon_name.strip():
                result[field] = taxon_name.strip()

        if not result:
            return None

        source = best.get('dataSourceTitleShort') or 'Global Names'
        source_id = best.get('dataSourceId')
        result['according_to'] = (
            f"{source} (Global Names data source {source_id})"
            if source_id else source)
        return result


class ChainedMatcher:
    """
    Run several matching backends in priority order; first match wins.

    Used to try the local database first and fall back to a remote backend
    (e.g. Global Names) only for names the local DB could not resolve. Mirrors
    the get_higher_taxa(name) interface and context-manager protocol of the
    individual backends.
    """

    def __init__(self, backends):
        self.backends = list(backends)

    def __enter__(self):
        for backend in self.backends:
            backend.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for backend in reversed(self.backends):
            backend.__exit__(exc_type, exc_val, exc_tb)
        return False

    def get_higher_taxa(self, scientific_name: str) -> Optional[Dict[str, str]]:
        for backend in self.backends:
            result = backend.get_higher_taxa(scientific_name)
            if result:
                return result
        return None


def process_reconcile(scientific_name: str, db_handler: MinimatchDB,
                      stats: bool, logger: logging.Logger) -> Optional[Dict[str, str]]:
    """
    Process reconciliation for a given scientific name.

    Args:
        scientific_name: Species name to reconcile
        db_handler: Database handler
        stats: Whether to show detailed stats
        logger: Logger instance

    Returns:
        Dictionary with taxonomy data or None if not found
    """
    logger.info(f"Reconciling: {scientific_name}")

    result = db_handler.get_higher_taxa(scientific_name)

    if result:
        logger.info(f"  ✓ Matched: {scientific_name} -> "
                   f"{result.get('kingdom_name', 'N/A')}/{result.get('genus_name', 'N/A')}")
        return result
    else:
        logger.warning(f"  ✗ No match for: {scientific_name}")
        return None


def reconcile(input_csv: str, output_csv: str, db_path: str,
             stats: bool, logger: logging.Logger,
             species_col: str = 'species_name',
             family_col: str = 'family_name',
             dataset_ids: Optional[List[int]] = None,
             gn_source_ids: Optional[List[int]] = None,
             source: str = 'local'):
    """
    Main reconciliation function.

    The local database is always tried first. Names it cannot resolve fall
    through to the fallback backend selected by ``source``.

    Args:
        input_csv: Input CSV file path
        output_csv: Output CSV file path
        db_path: Path to SQLite database
        stats: Whether to show statistics
        logger: Logger instance
        species_col: Column name for species scientific name
        family_col: Column name for family name
        dataset_ids: Local minitaxa dataset ids to match against, in priority
            order (first match wins)
        gn_source_ids: Global Names data source ids for the fallback backend
        source: Fallback backend for local misses: 'local' (no fallback) or
            'globalnames' (Global Names Verifier API)
    """
    dataset_ids = dataset_ids if dataset_ids else [1]
    gn_source_ids = gn_source_ids if gn_source_ids else []

    logger.info(f"Starting reconciliation: {input_csv} -> {output_csv}")
    logger.info(f"Using database: {db_path}")
    logger.info(f"Local dataset_ids (priority order): {dataset_ids}")

    # Local backend first; fall back to the chosen remote source for misses.
    backends = [MinimatchDB(db_path, dataset_ids)]
    if source == 'globalnames':
        backends.append(GlobalNamesVerifier(gn_source_ids))
        logger.info(f"Fallback: Global Names Verifier, data source(s): "
                    f"{gn_source_ids or 'best match'}")

    with ChainedMatcher(backends) as db_handler:
        fout = open(output_csv, 'w', newline='', encoding='utf-8')
        unmatched_records = []

        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # Use identity mapping (no config needed)
            fieldnames = list(reader.fieldnames)

            # Add reconciliation fields to output
            reconcile_headers = (list(RANK_TO_FIELD.values()) +
                               list(RANK_TO_FIELD_ZH.values()) +
                               ['according_to'])
            for field_name in reconcile_headers:
                if field_name not in fieldnames:
                    fieldnames.append(field_name)

            writer = csv.DictWriter(fout, fieldnames=fieldnames)
            writer.writeheader()

            reconcile_cache = {}
            row_count = 0

            for row in reader:
                row_count += 1
                if row_count % 10 == 0:
                    logger.info(f"Processing row {row_count}...")

                new_dict = {}
                row_matched = True
                current_species = None
                current_family = None

                for key, value in row.items():
                    new_dict[key] = value

                    # Track fields for matching
                    if key == species_col:
                        current_species = value
                    elif key == family_col:
                        current_family = value

                # Process reconciliation for species_name
                if current_species and current_species.strip():
                    if current_species not in reconcile_cache:
                        cache = process_reconcile(current_species, db_handler,
                                                 stats, logger)
                        if cache:
                            reconcile_cache[current_species] = cache
                            new_dict.update(cache)
                        else:
                            reconcile_cache[current_species] = None
                            row_matched = False
                    else:
                        if reconcile_cache[current_species] is not None:
                            logger.debug(f"  Cache hit: {current_species}")
                            new_dict.update(reconcile_cache[current_species])
                        else:
                            row_matched = False

                # Record unmatched species
                if not row_matched and current_species:
                    unmatched_records.append({
                        'species_name': current_species,
                        'family_name': current_family or ''
                    })

                writer.writerow(new_dict)

            logger.info(f"Processed {row_count} rows")
            logger.info(f"Unique species reconciled: {len(reconcile_cache)}")

            if stats and len(reconcile_cache) > 0:
                matched = sum(1 for v in reconcile_cache.values() if v)
                percentage = (matched / len(reconcile_cache)) * 100
                logger.info(f"Successfully matched: {matched}/{len(reconcile_cache)} "
                          f"({percentage:.1f}%)")
            elif stats:
                logger.info("No species found to reconcile")

        fout.close()
        logger.info(f"Output written to: {output_csv}")

        # Write unmatched records to log file
        if unmatched_records:
            log_file = output_csv.replace('.csv', '_unmatched.csv')
            with open(log_file, 'w', newline='', encoding='utf-8') as log_out:
                log_writer = csv.DictWriter(log_out,
                                           fieldnames=['species_name', 'family_name'])
                log_writer.writeheader()
                log_writer.writerows(unmatched_records)
            logger.warning(f"Unmatched records ({len(unmatched_records)}): {log_file}")
        else:
            logger.info("All records matched successfully!")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        prog='minimatch.py',
        description='Taxonomy reconciliation against the local minitaxa.db '
                    'database or the Global Names Verifier API',
        epilog='Examples:\n'
               '  %(prog)s input.csv output.csv\n'
               '  %(prog)s input.csv output.csv --db mydb.db\n'
               '  %(prog)s input.csv output.csv --stats -v\n'
               '  %(prog)s input.csv output.csv --source globalnames --gn-source 11\n'
               '  %(prog)s input.csv output.csv --species-col "物種學名" --family-col "科名"',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # Required positional arguments
    parser.add_argument('input_csv',
                       help='Input CSV file')
    parser.add_argument('output_csv',
                       help='Output CSV file')

    # Optional arguments
    parser.add_argument('--source',
                       choices=['local', 'globalnames'],
                       default='local',
                       help='Fallback backend for names not found in the local '
                            'database: "local" (no fallback, default) or '
                            '"globalnames" (Global Names Verifier API). The local '
                            'database is always tried first.')

    parser.add_argument('--db',
                       default='minitaxa.db',
                       help='SQLite database path (default: minitaxa.db). '
                            'Ignored when --source globalnames')

    parser.add_argument('--dataset-id',
                       default='1',
                       help='[--source local] Comma-separated minitaxa.db dataset '
                            'id(s) to match against, in priority order; first match '
                            'wins (default: 1, mycobank). Example: --dataset-id 1,3,2')

    parser.add_argument('--gn-source',
                       default='',
                       help='[--source globalnames] Comma-separated Global Names data '
                            'source id(s) for the fallback lookup '
                            '(e.g. 1=Catalogue of Life, 11=GBIF, 12=EOL). '
                            'Empty (default) lets Global Names pick the best source.')

    parser.add_argument('--species-col',
                       default='species_name',
                       help='Column name for species scientific name (default: species_name)')
    parser.add_argument('--family-col',
                       default='family_name',
                       help='Column name for family name (default: family_name)')

    parser.add_argument('--stats', '-s',
                       action='store_true',
                       help='Display reconciliation statistics')

    parser.add_argument('--verbose', '-v',
                       action='count',
                       default=0,
                       help='Increase verbosity (-v, -vv, -vvv)')

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()

    # Setup logging
    log_levels = [logging.WARNING, logging.INFO, logging.DEBUG]
    log_level = log_levels[min(args.verbose, len(log_levels) - 1)]

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    logger = logging.getLogger(__name__)

    # Use positional arguments for input/output
    input_csv = args.input_csv
    output_csv = args.output_csv

    # Validate input file
    try:
        with open(input_csv, 'r') as f:
            pass
    except FileNotFoundError:
        print(f"Error: Input file '{input_csv}' not found.", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Error: Permission denied reading '{input_csv}'.", file=sys.stderr)
        sys.exit(1)

    # Validate database file (the local backend always runs first)
    try:
        with open(args.db, 'r') as f:
            pass
    except FileNotFoundError:
        print(f"Error: Database file '{args.db}' not found.", file=sys.stderr)
        sys.exit(1)

    # Local minitaxa dataset ids (always used; the local backend runs first).
    try:
        dataset_ids = [int(x) for x in args.dataset_id.split(',') if x.strip()]
    except ValueError:
        print(f"Error: --dataset-id must be comma-separated integers, "
              f"got '{args.dataset_id}'.", file=sys.stderr)
        sys.exit(1)

    if not dataset_ids:
        print("Error: --dataset-id must contain at least one dataset id.",
              file=sys.stderr)
        sys.exit(1)

    # Global Names data source ids (fallback backend; empty = GN picks best).
    try:
        gn_source_ids = [int(x) for x in args.gn_source.split(',') if x.strip()]
    except ValueError:
        print(f"Error: --gn-source must be comma-separated integers, "
              f"got '{args.gn_source}'.", file=sys.stderr)
        sys.exit(1)

    reconcile(input_csv, output_csv, args.db, args.stats, logger,
             args.species_col, args.family_col, dataset_ids, gn_source_ids,
             args.source)
