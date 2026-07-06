# Local-first hybrid search in SQLite (FTS5 + sqlite-vec)

**Source (exact citation):** Alex Garcia (sqlite-vec author), "Hybrid full-text search and vector
search with SQLite", 2024. https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html
(primary/professional — the extension author's own reference implementation)

**Findings (faithful):**
- Full hybrid retrieval runs **entirely in-process in SQLite**: FTS5 provides BM25 (`bm25()`
  ranking function), sqlite-vec provides KNN over embeddings, and RRF fusion is a few lines of SQL
  over the two rank lists. No server, no extra service.
- FTS5 external-content tables index existing rows without duplicating text storage.
- Reference implementation demonstrates the exact pattern Omni needs: two top-k queries + a
  CTE computing `1/(k + rank)` per list, summed per document.

**Best parts to take for Omni:** this closes the feasibility question — the recommended M3
architecture (hybrid RRF + structured tables + wikilink graph joins) needs **zero new
infrastructure** beyond the SQLite database Omni already ships. Use external-content FTS5 over the
`chunks` table; keep embeddings, FTS, entities, links, and audit in the one omni.db.
