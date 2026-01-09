#!/usr/bin/env python3
"""
minimatch.py - Local taxonomy reconciliation using minitaxa.db

Queries local SQLite database instead of using APIs.
Uses mycobank (dataset_id=1) for higher taxa via closure table.
Uses taicol (dataset_id=2) for Chinese common names.

Usage: minimatch.py input.csv output.csv [--db DB_PATH] [--stats] [-v]
"""

import argparse
import sys
import csv
import logging
import sqlite3
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


class MinimatchDB:
    """Database handler for local taxonomy matching"""

    def __init__(self, db_path: str = 'minitaxa.db'):
        self.db_path = db_path
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

        Optimized: Single query to get all ancestors with Chinese names.
        Previously: 3-10 queries per species (1 + 1 + N for Chinese names)
        Now: 1 query per species

        Args:
            scientific_name: Species scientific name to look up

        Returns:
            Dictionary with taxonomy fields or None if not found
        """
        # Single optimized query to get all ancestors with Chinese names and dataset info
        self.cursor.execute("""
            WITH species AS (
                SELECT id, dataset_id
                FROM taxa
                WHERE name = ? AND dataset_id = 1
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
                WHERE t.dataset_id = 1
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
                AND t2.dataset_id = 2
            )
            LEFT JOIN taxa_common_name tcn ON (
                tcn.taxa_id = t2.id
                AND tcn.lang = 'zh'
            )
            GROUP BY at.taxa_name, at.rank, at.depth, at.dataset_name, at.dataset_version
            ORDER BY at.depth DESC
        """, (scientific_name,))

        ancestors = self.cursor.fetchall()

        if not ancestors:
            return None

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
             family_col: str = 'family_name'):
    """
    Main reconciliation function.

    Args:
        input_csv: Input CSV file path
        output_csv: Output CSV file path
        db_path: Path to SQLite database
        stats: Whether to show statistics
        logger: Logger instance
        species_col: Column name for species scientific name
        family_col: Column name for family name
    """
    logger.info(f"Starting reconciliation: {input_csv} -> {output_csv}")
    logger.info(f"Using database: {db_path}")

    with MinimatchDB(db_path) as db_handler:
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
        description='Local taxonomy reconciliation using minitaxa.db SQLite database',
        epilog='Examples:\n'
               '  %(prog)s input.csv output.csv\n'
               '  %(prog)s input.csv output.csv --db mydb.db\n'
               '  %(prog)s input.csv output.csv --stats -v\n'
               '  %(prog)s input.csv output.csv --species-col "物種學名" --family-col "科名"',
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # Required positional arguments
    parser.add_argument('input_csv',
                       help='Input CSV file')
    parser.add_argument('output_csv',
                       help='Output CSV file')

    # Optional arguments
    parser.add_argument('--db',
                       default='minitaxa.db',
                       help='SQLite database path (default: minitaxa.db)')

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

    # Validate database file
    try:
        with open(args.db, 'r') as f:
            pass
    except FileNotFoundError:
        print(f"Error: Database file '{args.db}' not found.", file=sys.stderr)
        sys.exit(1)

    reconcile(input_csv, output_csv, args.db, args.stats, logger,
             args.species_col, args.family_col)
