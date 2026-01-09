#!/usr/bin/env python3
import argparse
import csv
import sqlite3
from collections import defaultdict


class TaxaDatabase:
    """In-memory representation of existing taxa for efficient lookups."""

    def __init__(self, db_file, dataset_name=None):
        self.db_file = db_file
        self.dataset_name = dataset_name

        # In-memory mappings for fast lookups
        self.taxa_by_name = {}  # name -> list of taxa records
        self.taxa_by_source_id = {}  # source_id -> taxa record
        self.taxa_by_catalog = {}  # catalog_number -> taxa record
        self.ranks = {}  # rank_name -> rank_id
        self.dataset_id = None

        self._load_from_db()

    def _load_from_db(self):
        """Load existing data into in-memory mappings."""
        con = sqlite3.connect(self.db_file)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Load dataset info
        if self.dataset_name:
            cur.execute('SELECT id FROM dataset WHERE name = ?', (self.dataset_name,))
            row = cur.fetchone()
            if row:
                self.dataset_id = row['id']

        # Load all ranks
        cur.execute('SELECT id, name FROM taxa_rank')
        for row in cur.fetchall():
            self.ranks[row['name']] = row['id']

        # Load all taxa (filtered by dataset if specified)
        if self.dataset_id:
            cur.execute('''
                SELECT id, name, authors, year, rank_id, status_id,
                       source_id, catalog_number, link
                FROM taxa WHERE dataset_id = ?
            ''', (self.dataset_id,))
        else:
            cur.execute('''
                SELECT id, name, authors, year, rank_id, status_id,
                       source_id, catalog_number, link
                FROM taxa
            ''')

        for row in cur.fetchall():
            taxon = dict(row)

            # Index by name
            name = taxon['name']
            if name not in self.taxa_by_name:
                self.taxa_by_name[name] = []
            self.taxa_by_name[name].append(taxon)

            # Index by source_id
            if taxon['source_id']:
                self.taxa_by_source_id[taxon['source_id']] = taxon

            # Index by catalog_number
            if taxon['catalog_number']:
                self.taxa_by_catalog[taxon['catalog_number']] = taxon

        con.close()

        print(f"Loaded in-memory database:")
        print(f"  Total taxa: {sum(len(v) for v in self.taxa_by_name.values())}")
        print(f"  Unique names: {len(self.taxa_by_name)}")
        print(f"  By source_id: {len(self.taxa_by_source_id)}")
        print(f"  By catalog: {len(self.taxa_by_catalog)}")
        print(f"  Ranks: {len(self.ranks)}")
        if self.dataset_id:
            print(f"  Filtered by dataset: {self.dataset_name} (ID: {self.dataset_id})")
        print()

    def find_exact_match(self, name, source_id=None, catalog_number=None):
        """Find exact match by source_id, catalog_number, or name."""
        # Try source_id first (most specific)
        if source_id and source_id in self.taxa_by_source_id:
            return self.taxa_by_source_id[source_id]

        # Try catalog_number
        if catalog_number and catalog_number in self.taxa_by_catalog:
            return self.taxa_by_catalog[catalog_number]

        # Try exact name match
        if name in self.taxa_by_name:
            matches = self.taxa_by_name[name]
            if len(matches) == 1:
                return matches[0]
            # Multiple matches - ambiguous
            return None

        return None

    def find_by_name(self, name):
        """Find all taxa with the given name."""
        return self.taxa_by_name.get(name, [])

    def exists(self, name, source_id=None, catalog_number=None):
        """Check if taxon exists in database."""
        return self.find_exact_match(name, source_id, catalog_number) is not None


def parse_mycobank_csv(csv_file):
    """Parse MycoBank CSV file and yield taxa records."""
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def check_mycobank_data(csv_file, db_file, dataset_name=None, verbose=False):
    """Check which records from CSV are new vs existing."""

    # Load existing data into memory
    db = TaxaDatabase(db_file, dataset_name)

    # Statistics
    stats = {
        'total': 0,
        'exists_exact': 0,
        'exists_ambiguous': 0,
        'new': 0,
        'no_name': 0,
    }

    # Collections for reporting
    new_taxa = []
    existing_taxa = []
    ambiguous_taxa = []
    no_name_records = []

    print("Checking CSV records against database...\n")

    for row in parse_mycobank_csv(csv_file):
        stats['total'] += 1

        # Extract fields
        taxon_name = row.get('Taxon name', '').strip()
        mycobank_id = row.get('MycoBank #', '').strip() or None
        authors = row.get('Authors', '').strip() or None
        rank_name = row.get('Rank.Rank name', '').strip() or None

        # Skip if no taxon name
        if not taxon_name:
            stats['no_name'] += 1
            no_name_records.append(row)
            continue

        # Check if exists
        match = db.find_exact_match(taxon_name, mycobank_id, mycobank_id)

        if match:
            stats['exists_exact'] += 1
            existing_taxa.append({
                'csv': row,
                'db': match
            })
        else:
            # Check for ambiguous name matches
            name_matches = db.find_by_name(taxon_name)
            if len(name_matches) > 1:
                stats['exists_ambiguous'] += 1
                ambiguous_taxa.append({
                    'csv': row,
                    'matches': name_matches
                })
            elif len(name_matches) == 1 and not mycobank_id:
                # Exact name match but CSV has no source_id
                stats['exists_exact'] += 1
                existing_taxa.append({
                    'csv': row,
                    'db': name_matches[0]
                })
            else:
                # New record
                stats['new'] += 1
                new_taxa.append(row)

    # Print summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total records in CSV: {stats['total']}")
    print(f"  Existing (exact match): {stats['exists_exact']}")
    print(f"  Ambiguous (multiple name matches): {stats['exists_ambiguous']}")
    print(f"  New (not in database): {stats['new']}")
    print(f"  Skipped (no name): {stats['no_name']}")
    print()

    # Detailed output if verbose
    if verbose:
        if new_taxa:
            print("=" * 70)
            print(f"NEW TAXA ({len(new_taxa)} records)")
            print("=" * 70)
            for item in new_taxa[:20]:  # Show first 20
                print(f"  {item.get('Taxon name')} {item.get('Authors', '')} "
                      f"[{item.get('MycoBank #', 'no ID')}]")
            if len(new_taxa) > 20:
                print(f"  ... and {len(new_taxa) - 20} more")
            print()

        if ambiguous_taxa:
            print("=" * 70)
            print(f"AMBIGUOUS MATCHES ({len(ambiguous_taxa)} records)")
            print("=" * 70)
            for item in ambiguous_taxa[:10]:  # Show first 10
                csv_rec = item['csv']
                print(f"  CSV: {csv_rec.get('Taxon name')} {csv_rec.get('Authors', '')} "
                      f"[{csv_rec.get('MycoBank #', 'no ID')}]")
                print(f"    Matches in DB: {len(item['matches'])}")
                for match in item['matches'][:3]:
                    print(f"      - ID {match['id']}: {match['name']} "
                          f"[source: {match['source_id'] or 'none'}]")
            if len(ambiguous_taxa) > 10:
                print(f"  ... and {len(ambiguous_taxa) - 10} more")
            print()

    return {
        'stats': stats,
        'new_taxa': new_taxa,
        'existing_taxa': existing_taxa,
        'ambiguous_taxa': ambiguous_taxa,
        'no_name_records': no_name_records
    }


def export_new_taxa(new_taxa, output_file):
    """Export new taxa to a CSV file."""
    if not new_taxa:
        print("No new taxa to export.")
        return

    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        fieldnames = new_taxa[0].keys()
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_taxa)

    print(f"Exported {len(new_taxa)} new taxa to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Check MycoBank CSV against existing database',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Example usage:
  ./check-mycobank.py data/mycobank/MBList-short.csv
  ./check-mycobank.py data/mycobank/MBList.csv --dataset MycoBank -v
  ./check-mycobank.py data/mycobank/MBList.csv --export-new new-taxa.csv
        '''
    )

    parser.add_argument('csv_file', type=str, help='Path to MycoBank CSV file')
    parser.add_argument('--db', type=str, default='minitaxa.db',
                       help='Database file (default: minitaxa.db)')
    parser.add_argument('--dataset', type=str, default=None,
                       help='Filter by dataset name (e.g., MycoBank)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Show detailed output')
    parser.add_argument('--export-new', type=str, metavar='FILE',
                       help='Export new taxa to CSV file')

    args = parser.parse_args()

    print(f"CSV file: {args.csv_file}")
    print(f"Database: {args.db}")
    if args.dataset:
        print(f"Dataset filter: {args.dataset}")
    print()

    result = check_mycobank_data(args.csv_file, args.db, args.dataset, args.verbose)

    if args.export_new:
        export_new_taxa(result['new_taxa'], args.export_new)


if __name__ == '__main__':
    main()
