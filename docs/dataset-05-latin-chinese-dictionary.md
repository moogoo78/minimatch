# Dataset 5 — "latin-chinese dictionary"

A Latin ↔ Chinese fish-name dictionary covering the full world fish taxonomy,
imported into `minitaxa.db` as `dataset_id = 5`.

**Source URL:** <https://fishdb.sinica.edu.tw/AjaxTree/tree.php>

| Field | Value |
|-------|-------|
| `dataset.id` | **5** |
| `dataset.name` | `latin-chinese dictionary` |
| `dataset.version` | `26.06.24` |
| `dataset.description` | Latin-Chinese fish name dictionary, scraped from the fishdb AjaxTree world taxonomy tree https://fishdb.sinica.edu.tw/AjaxTree/tree.php |
| Total taxa | **38,284** |
| Chinese common names | 38,284 (100%) |
| Closure rows (dataset 5) | 324,733 |

## Source & provenance

- **Origin:** Academia Sinica Taiwan Fish Database — world taxonomy tree
  (世界魚類分類階層樹狀名錄), <https://fishdb.sinica.edu.tw/AjaxTree/tree.php>.
- The tree is lazy-loaded from `xml.php?id=<id>` (root `id=0`); species leaves
  link to `redirect.php?tree=w&id=<id>` (ids like `LH00006`).
- **Crawl:** the entire tree was first walked through a real browser session to
  avoid bot-blocking, then rebuilt host-side with a browser User-Agent + Referer
  at a polite rate (no blocks encountered). Raw result saved to
  `fish_tree_world.json` (5,561 internal nodes + 32,723 species, matching the
  site's stated species total exactly).
- See the reference note `fishdb-ajaxtree-api` for endpoint details and the
  XML parsing gotcha (literal `>` inside `<font class=c8>` 台/陸 badges).

## Schema mapping

Each tree node became one `taxa` row. Conventions follow the existing
`fishdb`/`taicol` datasets:

| Tree data | Column |
|-----------|--------|
| Latin / scientific name | `taxa.name` |
| Chinese name | `taxa_common_name.name` (`lang='zh'`, `sort=1`) |
| Authors, year (species) | `taxa.authors`, `taxa.year` |
| Rank (from label keyword) | `taxa.rank_id` |
| Validity | `taxa.status_id = 8` (valid) |
| fishdb node id (`LH…`, `c…`) | `taxa.source_id` |
| Species detail URL | `taxa.link` |
| Original label + 台/陸 flags | `taxa.source_data` (JSON) |
| Hierarchy | `taxa_closure` (ancestor/descendant/depth, self at depth 0) |

`source_data` example:
`{"label": "布氏黏盲鰻(蒲氏黏盲鰻) Eptatretus burgeri (Girard, 1855)台陸", "tw": true, "cn": true}`

## Rank breakdown

| Rank | `rank_id` | Count |
|------|----------:|------:|
| Kingdom | 3 | 1 *(hand-added)* |
| Phylum | 7 | 1 *(hand-added)* |
| Class | 11 | 7 |
| Subclass | 12 | 9 |
| Order | 16 | 62 |
| Suborder | 17 | 81 |
| Family | 21 | 515 |
| Genus | 25 | 4,885 |
| Species | 31 | 32,723 |
| **Total** | | **38,284** |

Notes:
- The source tree is **not uniform-depth** — e.g. *Myxini* (hagfish) goes
  Class → Order directly, skipping Subclass/Suborder. Rank is therefore derived
  from the label keyword (`class`/`subclass`/`order`/…/`Genus`), not from depth.
- 2 empty fossil placeholder nodes (`order 0亞目 0科 0屬 0種`) were skipped.
- **Species author/year coverage:** 32,721/32,723 have `authors`,
  32,722/32,723 have `year` (a couple of entries lack a citation in the source).
- **Distribution flags** (from the 台/陸 badges): 3,133 species flagged as
  occurring in Taiwan (台), 3,951 in mainland China (陸), stored in `source_data`.

## Hand-added higher taxa (Kingdom + Phylum)

The source tree tops out at **Class**, so Kingdom and Phylum were added manually
so that every taxon resolves to a complete lineage:

```
Animalia (Kingdom, rank 3, id 833843, 動物界)
└── Chordata (Phylum, rank 7, id 833844, 脊索動物門)
    └── <the 7 classes and everything below them>
```

- Both nodes were inserted into dataset 5 with `status_id = 8` and a marker
  `source_data = {"note": "added higher taxon"}` (no fishdb `source_id`/`link`).
- `taxa_closure` was extended so **every existing taxon** gained both as
  ancestors at the correct depth: Chordata at *(class-depth + 1)*, Animalia at
  *(class-depth + 2)*. 76,567 closure rows were added (2 self-rows, the
  Animalia→Chordata edge, and 2 rows per existing taxon).
- Verified: **0 taxa** are missing a Kingdom or Phylum ancestor.

Because the tree only contains fishes, Animalia/Chordata are valid for **all**
members (including the fossil classes *Placodermi* and *Acanthodii*).

Example full lineage (a hagfish species):

| depth | rank | latin | chinese |
|------:|------|-------|---------|
| 6 | Kingdom | Animalia | 動物界 |
| 5 | Phylum | Chordata | 脊索動物門 |
| 4 | Class | Myxini | 盲鰻綱 |
| 3 | Order | Myxiniformes | 盲鰻目 |
| 2 | Family | Myxinidae | 盲鰻科 |
| 1 | Genus | Eptatretus | 黏盲鰻屬 |
| 0 | Species | Eptatretus alastairi | 阿拉氏黏盲鰻 |

## Usage with `minimatch.py`

```bash
python3 minimatch.py input.csv output.csv --dataset-id 5 --stats
```

Resolves each species to its higher taxa via the closure table, e.g.:

```
Eptatretus alastairi → Animalia | Chordata | Myxini | Myxiniformes | Myxinidae | Eptatretus
```

Higher-taxon **Chinese** names in the output come from the `taicol`
(dataset 2) join inside `minimatch.py`, not from this dataset's own
`taxa_common_name` rows.

## Caveats

- The site's headline genus total (5,032) is higher than the **4,885** genus
  *nodes* present in the browsable tree; species matched the headline exactly
  (32,723) and all crawled nodes are accounted for, so nothing was dropped —
  the gap is a property of the source data.
- Author parentheses are dropped to match the existing `fishdb` convention
  (the original string is preserved in `source_data.label`).

## Files

| File | Purpose |
|------|---------|
| `fish_tree_world.json` | Raw crawled tree (label + link per node) |
| `import_latin_chinese.py` | Builds dataset 5 from the JSON (`--dry-run` supported) |
| `add_higher_taxa.py` | Adds Animalia/Chordata + closure (`--dry-run`, idempotent guard) |
| `minitaxa-260624.db` | Backup taken **before** dataset 5 was created |
