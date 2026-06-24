#!/usr/bin/env python3
"""
Add Kingdom Animalia + Phylum Chordata above every taxon in dataset 5
("latin-chinese dictionary"), wiring them into taxa_closure so every existing
taxon gains them as ancestors at the correct depth.

  Animalia (Kingdom, rank 3)
    Chordata (Phylum, rank 7)
      <existing 7 classes and everything below>

Usage:  python3 add_higher_taxa.py [--dry-run] [--db minitaxa.db]
"""
import argparse, json, sqlite3, sys

DATASET_ID = 5
STATUS_VALID = 8
KINGDOM_RANK = 3      # Kingdom
PHYLUM_RANK = 7       # Phylum
NODES = [
    ("Animalia", "動物界", KINGDOM_RANK),
    ("Chordata", "脊索動物門", PHYLUM_RANK),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default="minitaxa.db")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")

    # guard: don't double-add
    cur.execute("SELECT name FROM taxa WHERE dataset_id=? AND name IN ('Animalia','Chordata') "
                "AND rank_id IN (?,?)", (DATASET_ID, KINGDOM_RANK, PHYLUM_RANK))
    existing = [r["name"] for r in cur.fetchall()]
    if existing:
        print("Already present in dataset %d: %s -- aborting." % (DATASET_ID, existing))
        conn.close(); sys.exit(1)

    # current taxa in dataset 5 and each one's distance to its class (= current max depth)
    cur.execute("""
        SELECT c.descendant_id AS id, MAX(c.depth) AS m
        FROM taxa_closure c
        JOIN taxa t ON t.id = c.descendant_id
        WHERE t.dataset_id = ?
        GROUP BY c.descendant_id
    """, (DATASET_ID,))
    rows = cur.fetchall()
    n_taxa = len(rows)
    print("existing taxa in dataset %d: %d" % (DATASET_ID, n_taxa))
    # new closure rows: for each taxon X -> (Chordata,X,m+1) and (Animalia,X,m+2)
    print("will insert 2 taxa, 2 common names, and %d closure rows "
          "(2 self + 1 edge + %d)" % (3 + 2 * n_taxa, 2 * n_taxa))

    if args.dry_run:
        # show what the deepest taxon will look like
        mx = max(r["m"] for r in rows)
        print("max current depth (a class-rooted leaf): %d -> Chordata depth %d, "
              "Animalia depth %d" % (mx, mx + 1, mx + 2))
        conn.close(); print("[dry-run] no changes."); return

    try:
        # insert Animalia, Chordata
        ids = {}
        for name, zh, rank in NODES:
            cur.execute(
                "INSERT INTO taxa(name,authors,year,rank_id,status_id,dataset_id,"
                "source_id,link,source_data) VALUES(?,?,?,?,?,?,?,?,?)",
                (name, None, None, rank, STATUS_VALID, DATASET_ID, None, None,
                 json.dumps({"note": "added higher taxon"}, ensure_ascii=False)))
            ids[name] = cur.lastrowid
            cur.execute("INSERT INTO taxa_common_name(taxa_id,name,lang,sort) "
                        "VALUES(?,?,?,?)", (ids[name], zh, "zh", 1))
        animalia, chordata = ids["Animalia"], ids["Chordata"]

        closure = [
            (animalia, animalia, 0),
            (chordata, chordata, 0),
            (animalia, chordata, 1),
        ]
        for r in rows:
            m = r["m"]
            closure.append((chordata, r["id"], m + 1))
            closure.append((animalia, r["id"], m + 2))

        cur.executemany(
            "INSERT INTO taxa_closure(ancestor_id,descendant_id,depth) VALUES(?,?,?)",
            closure)
        conn.commit()
        print("done. Animalia id=%d, Chordata id=%d, closure rows added=%d"
              % (animalia, chordata, len(closure)))
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
