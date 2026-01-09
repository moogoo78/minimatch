#!/usr/bin/env python3
import argparse
import csv
import sqlite3
import configparser
from collections import Counter


def load_existing_ranks(db_file):
    """Load existing ranks from database into a set for fast lookup."""
    con = sqlite3.connect(db_file)
    cur = con.cursor()

    cur.execute('SELECT name, sort FROM taxa_rank ORDER BY sort')
    ranks = {}
    for row in cur.fetchall():
        ranks[row[0]] = row[1]

    con.close()
    return ranks


def parse_mycobank_csv(csv_file):
    """Parse MycoBank CSV file and yield rank information."""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rank_name = row.get('Rank.Rank name', '').strip()
            taxon_name = row.get('Taxon name', '').strip()
            if rank_name:
                yield {
                    'rank': rank_name,
                    'taxon': taxon_name,
                    'id': row.get('ID', '').strip(),
                    'mycobank': row.get('MycoBank #', '').strip()
                }


def check_ranks(csv_file, db_file, show_examples=True, max_examples=5):
    """Check which ranks from CSV are missing in database."""

    print(f"Loading existing ranks from database...\n")
    existing_ranks = load_existing_ranks(db_file)

    print(f"Existing ranks in database ({len(existing_ranks)}):")
    for rank, sort_order in sorted(existing_ranks.items(), key=lambda x: x[1]):
        print(f"  [{sort_order:3d}] {rank}")
    print()

    print(f"Analyzing ranks in CSV file...\n")

    # Statistics
    rank_counts = Counter()
    new_ranks = {}  # rank -> list of example taxa
    existing_rank_counts = Counter()

    for record in parse_mycobank_csv(csv_file):
        rank = record['rank']
        rank_counts[rank] += 1

        if rank in existing_ranks:
            existing_rank_counts[rank] += 1
        else:
            if rank not in new_ranks:
                new_ranks[rank] = []
            if len(new_ranks[rank]) < max_examples:
                new_ranks[rank].append(record)

    # Summary
    total_records = sum(rank_counts.values())

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total records with ranks: {total_records}")
    print(f"Unique ranks in CSV: {len(rank_counts)}")
    print(f"  Existing in database: {len(existing_rank_counts)}")
    print(f"  NEW (not in database): {len(new_ranks)}")
    print()

    if existing_rank_counts:
        print("=" * 70)
        print("EXISTING RANKS (already in database)")
        print("=" * 70)
        for rank, count in sorted(existing_rank_counts.items(),
                                  key=lambda x: existing_ranks[x[0]]):
            sort_order = existing_ranks[rank]
            print(f"  [{sort_order:3d}] {rank:<20} : {count:6d} records")
        print()

    if new_ranks:
        print("=" * 70)
        print(f"NEW RANKS (not in database) - {len(new_ranks)} ranks")
        print("=" * 70)

        for rank in sorted(new_ranks.keys()):
            count = rank_counts[rank]
            print(f"\n  {rank} ({count} records)")

            if show_examples:
                examples = new_ranks[rank]
                print(f"    Examples:")
                for ex in examples:
                    taxon_info = ex['taxon']
                    id_info = ex['mycobank'] or ex['id'] or 'no ID'
                    print(f"      - {taxon_info} [{id_info}]")

                if count > len(examples):
                    print(f"      ... and {count - len(examples)} more")
        print()

    return {
        'existing_ranks': existing_ranks,
        'new_ranks': list(new_ranks.keys()),
        'rank_counts': dict(rank_counts),
        'existing_rank_counts': dict(existing_rank_counts)
    }


def load_config_mapping(ini_file='mycobank.ini'):
    """Load rank mappings from config file."""
    config = configparser.ConfigParser()
    config.read(ini_file)

    rank_map = {}
    if 'ranks' in config:
        for abbrev, sort_value in config['ranks'].items():
            if not sort_value or sort_value.startswith('#'):
                continue
            try:
                rank_map[abbrev] = int(sort_value)
            except ValueError:
                pass

    return rank_map


def suggest_rank_order(new_ranks, rank_counts, config_mapping=None):
    """Suggest sort order for new ranks based on config or standard taxonomic hierarchy."""

    # Standard taxonomic rank hierarchy (lower number = higher rank)
    standard_order = {
        'domain': 10,
        'superkingdom': 10,
        'kingdom': 30,
        'regn.': 30,
        'subkingdom': 40,
        'subregn.': 41,
        'phylum': 70,
        'division': 71,
        'div.': 71,
        'subphylum': 80,
        'subdivision': 81,
        'subdiv.': 81,
        'class': 110,
        'cl.': 110,
        'subclass': 120,
        'subcl.': 120,
        'order': 160,
        'ordo': 160,
        'suborder': 170,
        'subordo': 170,
        'family': 210,
        'fam.': 210,
        'subdivf.': 211,
        'subfamily': 220,
        'subfam.': 220,
        'tribe': 230,
        'tr.': 230,
        'subtribe': 240,
        'subtr.': 240,
        'genus': 250,
        'gen.': 250,
        'subgenus': 260,
        'subgen.': 260,
        'section': 270,
        'sect.': 270,
        'subsection': 280,
        'subsect.': 280,
        'series': 290,
        'ser.': 290,
        'subseries': 300,
        'subser.': 300,
        'species': 310,
        'sp.': 310,
        'stirps': 311,
        'strips': 311,
        'subspecies': 320,
        'subsp.': 320,
        'variety': 330,
        'var.': 330,
        'subvariety': 340,
        'subvar.': 340,
        'form': 350,
        'f.': 350,
        'forma specialis': 351,
        'f.sp.': 351,
        'subform': 360,
        'subf.': 360,
        'race': 500,
        '-': 999,
    }

    suggestions = []
    for rank in new_ranks:
        rank_lower = rank.lower()

        # Try config mapping first, then standard order
        if config_mapping and rank in config_mapping:
            suggested_sort = config_mapping[rank]
        elif rank_lower in standard_order:
            suggested_sort = standard_order[rank_lower]
        else:
            suggested_sort = 999

        count = rank_counts.get(rank, 0)
        suggestions.append((rank, suggested_sort, count))

    return sorted(suggestions, key=lambda x: x[1])


def export_insert_sql(new_ranks, rank_counts, output_file, config_mapping=None):
    """Generate SQL INSERT statements for new ranks."""

    suggestions = suggest_rank_order(new_ranks, rank_counts, config_mapping)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("-- SQL to insert new taxonomic ranks\n")
        f.write("-- Generated by check-ranks.py\n\n")

        for rank, sort_order, count in suggestions:
            f.write(f"-- {rank}: {count} records in source data\n")
            f.write(f"INSERT INTO taxa_rank (name, sort) VALUES ('{rank}', {sort_order});\n")

        f.write("\n-- Verify ranks\n")
        f.write("SELECT * FROM taxa_rank ORDER BY sort;\n")

    print(f"Generated SQL INSERT statements in: {output_file}")
    print("\nSuggested rank order (you may want to adjust):")
    for rank, sort_order, count in suggestions:
        print(f"  [{sort_order:3d}] {rank:<20} ({count} records)")


def main():
    parser = argparse.ArgumentParser(
        description='Check taxonomic ranks in CSV against database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Example usage:
  # Basic check
  ./check-ranks.py data/mycobank/MBList-short.csv

  # Hide examples
  ./check-ranks.py data/mycobank/MBList.csv --no-examples

  # Generate SQL to insert missing ranks
  ./check-ranks.py data/mycobank/MBList.csv --export-sql insert-ranks.sql

  # More examples per rank
  ./check-ranks.py data/mycobank/MBList.csv --max-examples 10
        '''
    )

    parser.add_argument('csv_file', type=str,
                       help='Path to MycoBank CSV file')
    parser.add_argument('--db', type=str, default='minitaxa.db',
                       help='Database file (default: minitaxa.db)')
    parser.add_argument('--no-examples', action='store_true',
                       help='Do not show example taxa for each rank')
    parser.add_argument('--max-examples', type=int, default=5,
                       help='Maximum examples per rank (default: 5)')
    parser.add_argument('--export-sql', type=str, metavar='FILE',
                       help='Export SQL INSERT statements for new ranks')
    parser.add_argument('--config', type=str, default='mycobank.ini',
                       help='Config file with rank mappings (default: mycobank.ini)')

    args = parser.parse_args()

    print(f"CSV file: {args.csv_file}")
    print(f"Database: {args.db}")
    print()

    result = check_ranks(
        args.csv_file,
        args.db,
        show_examples=not args.no_examples,
        max_examples=args.max_examples
    )

    if args.export_sql and result['new_ranks']:
        print()
        # Load config mapping for better sort order suggestions
        config_mapping = load_config_mapping(args.config)
        if config_mapping:
            print(f"Using rank mappings from {args.config}")
        export_insert_sql(
            result['new_ranks'],
            result['rank_counts'],
            args.export_sql,
            config_mapping
        )


if __name__ == '__main__':
    main()
