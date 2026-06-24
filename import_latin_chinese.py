#!/usr/bin/env python3
"""
Import the fishdb AjaxTree world fish taxonomy tree (fish_tree_world.json)
into minitaxa.db as a new dataset named "latin-chinese dictionary".

- taxa.name           = Latin / scientific name
- taxa_common_name    = Chinese name (lang='zh', sort=1)
- taxa_closure        = full ancestor/descendant closure (self at depth 0)
- status_id           = 8 (valid), matching the existing fishdb dataset

Usage:
    python3 import_latin_chinese.py --dry-run      # parse + report only
    python3 import_latin_chinese.py                # actually import
"""
import argparse, json, re, sqlite3, sys, collections

JSON_PATH = "fish_tree_world.json"
DATASET_NAME = "latin-chinese dictionary"
DATASET_VERSION = "26.06.24"
DATASET_DESC = ("Latin-Chinese fish name dictionary, scraped from the fishdb "
                "AjaxTree world taxonomy tree "
                "https://fishdb.sinica.edu.tw/AjaxTree/tree.php")
STATUS_VALID = 8

RANK_ID = {
    "superclass": 10, "class": 11, "subclass": 12, "infraclass": 13,
    "superorder": 15, "order": 16, "suborder": 17, "infraorder": 18,
    "superfamily": 20, "family": 21, "subfamily": 22, "tribe": 23,
    "genus": 25, "subgenus": 26,
}
RANK_SPECIES = 31
KEYWORDS = ["superclass", "subclass", "infraclass", "class",
            "superorder", "suborder", "infraorder", "order",
            "superfamily", "subfamily", "family",
            "subgenus", "genus", "tribe"]
# lowercase author particles that must NOT be mistaken for an infraspecific epithet
PARTICLES = {"de", "del", "della", "der", "den", "van", "von", "da", "dos",
             "das", "di", "du", "la", "le", "el", "ten", "ter", "y", "do"}

count_tok = re.compile(r"^\d")          # count tokens start with a digit
kw_res = {k: re.compile(r"(?<![a-z])" + k + r"(?![a-z])", re.I) for k in KEYWORDS}


def parse_internal(label):
    """Return (latin, chinese, rank_id) for an internal node, or None to skip."""
    rank_id = None
    pos = None
    for k in KEYWORDS:
        m = kw_res[k].search(label)
        if m and (pos is None or m.start() < pos):
            pos, rank_id, kwend = m.start(), RANK_ID[k], m.end()
    if rank_id is None:
        return None
    before = label[:pos].split()
    after = label[kwend:].split()
    chinese = before[0] if before and not count_tok.match(before[0]) else ""
    latin_toks = []
    for t in after:
        if count_tok.match(t):
            break
        latin_toks.append(t)
    latin = " ".join(latin_toks).strip()
    if not latin and not chinese:
        return None
    return latin, chinese, rank_id


def parse_species(label):
    """Return (latin, chinese, authors, year, tw, cn)."""
    tw = "台" in label
    cn = "陸" in label
    s = label.rstrip("台陸 ").rstrip()
    toks = s.split()
    chinese = toks[0] if toks else ""
    rest = toks[1:]
    name = []
    if rest:
        name.append(rest[0])            # Genus
    if len(rest) > 1:
        name.append(rest[1])            # species epithet
    i = 2
    # optional infraspecific epithet(s): lowercase, not an author particle
    while i < len(rest):
        t = rest[i]
        if re.fullmatch(r"[a-z-]+", t) and t not in PARTICLES:
            name.append(t)
            i += 1
        else:
            break
    latin = " ".join(name).strip()
    auth_part = " ".join(rest[i:]).strip()
    year = None
    ym = re.findall(r"\b(\d{4})\b", auth_part)
    if ym:
        year = int(ym[-1])
    authors = auth_part.strip("()")
    authors = re.sub(r",?\s*\d{4}\s*\)?\s*$", "", authors).strip().strip("(),")
    authors = authors or None
    return latin, chinese, authors, year, tw, cn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default="minitaxa.db")
    args = ap.parse_args()

    data = json.load(open(JSON_PATH, encoding="utf-8"))

    # ---- parse whole tree into flat records with parent links ----
    records = []          # dict: idx, parent_idx, name, chinese, authors, year,
                          #       rank_id, source_id, link, source_data
    stats = collections.Counter()
    skipped = []

    def walk(node, parent_idx):
        label = node.get("label", "")
        if node.get("type") == "species":
            latin, chinese, authors, year, tw, cn = parse_species(label)
            rank_id = RANK_SPECIES
            link = node.get("link")
        else:
            parsed = parse_internal(label)
            if parsed is None:
                skipped.append(label)
                # still recurse children under the same parent
                for c in node.get("children", []):
                    walk(c, parent_idx)
                return
            latin, chinese, rank_id = parsed
            authors = year = None
            tw = cn = False
            link = node.get("link")
        if not latin:
            latin = chinese or "(unnamed)"
        idx = len(records)
        sd = {"label": label}
        if tw: sd["tw"] = True
        if cn: sd["cn"] = True
        records.append(dict(idx=idx, parent=parent_idx, name=latin,
                            chinese=chinese, authors=authors, year=year,
                            rank_id=rank_id, source_id=node.get("id"),
                            link=link, source_data=json.dumps(sd, ensure_ascii=False)))
        stats[rank_id] += 1
        for c in node.get("children", []):
            walk(c, idx)

    for root in data["tree"]:
        walk(root, None)

    rank_name = {11:"Class",12:"Subclass",13:"Infraclass",15:"Superorder",
                 16:"Order",17:"Suborder",18:"Infraorder",20:"Superfamily",
                 21:"Family",22:"Subfamily",23:"Tribe",25:"Genus",
                 26:"Subgenus",31:"Species",10:"Superclass"}
    print("Parsed records:", len(records), " skipped(empty fossil):", len(skipped))
    for rid in sorted(stats):
        print("  %-12s %d" % (rank_name.get(rid, rid), stats[rid]))
    n_zh = sum(1 for r in records if r["chinese"])
    print("with Chinese name:", n_zh, "/", len(records))

    # show a few parsed samples per rank
    seen = set()
    print("\n--- sample parses ---")
    for r in records:
        key = r["rank_id"]
        if key in seen: continue
        seen.add(key)
        print("  [%s] name=%r zh=%r auth=%r yr=%r" %
              (rank_name.get(key), r["name"], r["chinese"], r["authors"], r["year"]))
    if skipped:
        print("\nskipped labels (sample):", skipped[:5])

    if args.dry_run:
        print("\n[dry-run] no DB changes.")
        return

    # ---- write to DB ----
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    try:
        cur.execute("INSERT INTO dataset(name,version,description) VALUES(?,?,?)",
                    (DATASET_NAME, DATASET_VERSION, DATASET_DESC))
        ds_id = cur.lastrowid
        print("\nnew dataset id:", ds_id)

        taxa_ids = [None] * len(records)
        common = []
        for r in records:
            cur.execute(
                "INSERT INTO taxa(name,authors,year,rank_id,status_id,dataset_id,"
                "source_id,link,source_data) VALUES(?,?,?,?,?,?,?,?,?)",
                (r["name"], r["authors"], r["year"], r["rank_id"], STATUS_VALID,
                 ds_id, r["source_id"], r["link"], r["source_data"]))
            tid = cur.lastrowid
            taxa_ids[r["idx"]] = tid
            if r["chinese"]:
                common.append((tid, r["chinese"], "zh", 1))

        cur.executemany(
            "INSERT INTO taxa_common_name(taxa_id,name,lang,sort) VALUES(?,?,?,?)",
            common)

        # closure: walk parent chain for each record
        closure = []
        for r in records:
            tid = taxa_ids[r["idx"]]
            closure.append((tid, tid, 0))
            depth = 1
            p = r["parent"]
            while p is not None:
                closure.append((taxa_ids[p], tid, depth))
                depth += 1
                p = records[p]["parent"]
        cur.executemany(
            "INSERT INTO taxa_closure(ancestor_id,descendant_id,depth) VALUES(?,?,?)",
            closure)

        conn.commit()
        print("inserted taxa:", len(records),
              " common_names:", len(common),
              " closure_rows:", len(closure))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
