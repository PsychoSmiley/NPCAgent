// NPCAgent run-log collector. One SQLite-backed Durable Object = the whole archive.
//
// One row per RUN, blind-upserted daily, keyed by a 128-bit client capability id (rid, crypto-random).
// - POST /submit?rid=<32hex>&day=N  upserts that run's row (INSERT ... ON CONFLICT DO UPDATE, day-guarded).
//   The rid is unguessable, so a client can only overwrite ITS OWN row; it can never read or enumerate others'.
//   rid is REQUIRED (no legacy write path) so every write is envelope-validated + storage-capped.
// - POST /withdraw?rid=<32hex>  deletes exactly that run (capability-scoped self-erasure).
// Public: /submit (SUBMIT_KEY), /count (aggregate). Owner-only via Authorization: Bearer OWNER_KEY (a wrangler
// secret, never shipped to the browser, kept OUT of the URL so it is never logged): /list, /export, /delete, /purge.
// There is no client read path by design.

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "POST,GET,OPTIONS",
  "access-control-allow-headers": "content-type,authorization",
  "access-control-max-age": "86400",   // only covers the owner routes: /submit sends text/plain and /withdraw sends no
                                       // headers, so both are simple requests and are never preflighted at all. Moving
                                       // rid or day into a header would reintroduce a preflight (Chromium caps this at 7200s).
};
const MAX_BODY = 800 * 1024;        // 800 KB/run row (SQLite row limit is 2 MB); caps spam blast radius
const DB_CUTOFF = 900 * 1024 * 1024; // stop accepting NEW runs near the 1 GB PER-DURABLE-OBJECT cap on Workers Free
                                     // (the 5 GB free figure is account-wide; one DO binds first). Raise to ~9 GB on Paid.
const RID = /^[0-9a-f]{32}$/;

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...CORS } });
}
function bearer(req) { const h = req.headers.get("authorization") || ""; return h.startsWith("Bearer ") ? h.slice(7) : ""; }
function ctEq(a, b) {            // constant-time string compare (paired with header-based key so it isn't logged)
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let r = 0; for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
function tooBig(req, body) {     // reject on content-length before buffering, then byte-check the buffered body
  const clen = Number(req.headers.get("content-length") || 0);
  if (Number.isFinite(clen) && clen > MAX_BODY) return true;
  return body !== undefined && new TextEncoder().encode(body).length > MAX_BODY;
}

export class LogStore {
  constructor(ctx) {
    this.sql = ctx.storage.sql;
    this.sql.exec("CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER, ua TEXT, meta TEXT, bytes INTEGER, body TEXT)");
    this.sql.exec("CREATE TABLE IF NOT EXISTS runs2(rid TEXT PRIMARY KEY, created INTEGER, updated INTEGER, ua TEXT, meta TEXT, day INTEGER, saves INTEGER, bytes INTEGER, body TEXT)");
    this.sql.exec("CREATE INDEX IF NOT EXISTS runs2_updated ON runs2(updated)");   // /list orders by this; without it the owner's listing sorts the whole table
  }

  // fail CLOSED on BOTH paths: `|| 0` meant an absent or NaN databaseSize silently disabled the guard, which is the
  // exact outcome failing closed is meant to prevent. (It measures USED pages - page_count minus freelist - so it
  // drops after /withdraw and /purge and the archive correctly reopens without a VACUUM.)
  dbSize() { try { const n = this.sql.databaseSize; return Number.isFinite(n) ? n : Infinity; } catch (_) { return Infinity; } }

  async fetch(req) {
    const url = new URL(req.url);
    const now = Date.now();

    if (url.pathname === "/submit" && req.method === "POST") {
      if (tooBig(req)) return json({ ok: false, err: "too_large" }, 413);   // pre-body content-length gate (avoids buffering a huge body into the DO)
      const rid = url.searchParams.get("rid") || "";
      if (!RID.test(rid)) return json({ ok: false, err: "bad_rid" }, 400);  // rid required: no unguarded legacy write path
      const body = await req.text();
      if (tooBig(req, body)) return json({ ok: false, err: "too_large" }, 413);
      let parsed; try { parsed = JSON.parse(body); } catch { return json({ ok: false, err: "bad_json" }, 400); }
      if (!parsed || typeof parsed !== "object" || !Number.isInteger(parsed.day) || !Array.isArray(parsed.sharegpt))
        return json({ ok: false, err: "bad_envelope" }, 400);
      const nd = Number(url.searchParams.get("day"));
      const day = Number.isFinite(nd) ? Math.max(0, Math.floor(nd)) : 0;   // reject Infinity/NaN so the day-guard can't be bricked
      const meta = (url.searchParams.get("meta") || "").slice(0, 300);
      const ua = (req.headers.get("user-agent") || "").slice(0, 200);
      const bytes = new TextEncoder().encode(body).length;
      let row, exists = true;   // default TRUE: if the existence probe itself throws, "unknown" must not read as "new run" and earn a 507, which the client latches permanently
      try {
        // the SELECT belongs inside the guard too: an uncaught throw here is a CORS-less 500 that the browser reports
        // as "Failed to fetch", which latches nothing, so every tab retries it every 3 minutes for the rest of the run
        const prior = this.sql.exec("SELECT bytes FROM runs2 WHERE rid=?", rid).toArray()[0];
        exists = prior !== undefined;
        // Past the cutoff, refuse GROWTH from anyone - not just new runs. Existing rows kept expanding toward 800 KB
        // each, so the guard could be walked straight past it. A shrinking or flat update is still accepted, which
        // lets a run that trimmed itself keep archiving instead of being locked out for having once been large.
        if (this.dbSize() > DB_CUTOFF && bytes > (prior ? prior.bytes || 0 : 0))
          return json({ ok: false, err: "archive_full" }, 507);
        this.sql.exec(
          `INSERT INTO runs2(rid,created,updated,ua,meta,day,saves,bytes,body)
           VALUES (?,?,?,?,?,?,1,?,?)
           ON CONFLICT(rid) DO UPDATE SET
             updated=excluded.updated, meta=excluded.meta, day=excluded.day,
             saves=runs2.saves+1, bytes=excluded.bytes, body=excluded.body
           WHERE excluded.day >= runs2.day`,
          rid, now, now, ua, meta, day, bytes, body);
        row = this.sql.exec("SELECT day,saves FROM runs2 WHERE rid=?", rid).toArray()[0] || {};
      } catch (_) {
        // An uncaught DO exception is a runtime 500 with NO CORS headers: the browser reports it as "Failed to fetch",
        // nothing latches, and every tab retries forever. So classify it here instead, by re-measuring rather than by
        // message text. Only a genuinely full archive may return 507, which the client latches permanently; everything
        // else gets the retryable 503. Both `!exists` and Number.isFinite exist to keep transient errors out of 507 -
        // an already-stored run is exempt from the fullness gate, and an unmeasurable dbSize reports Infinity.
        const n = this.dbSize();
        const full = !exists && Number.isFinite(n) && n > DB_CUTOFF;
        return json({ ok: false, err: full ? "archive_full" : "write_failed" }, full ? 507 : 503);
      }
      return json({ ok: true, day: row.day, saves: row.saves, stored: row.day === day });   // the day-guard can silently skip the update; say so instead of letting the client report a stale day as "archived"
    }

    if (url.pathname === "/withdraw" && req.method === "POST") {
      const rid = url.searchParams.get("rid") || "";
      if (!RID.test(rid)) return json({ ok: false, err: "bad_rid" }, 400);
      try { this.sql.exec("DELETE FROM runs2 WHERE rid=?", rid); }   // capability-scoped: only the holder of this rid can erase this run
      catch (_) { return json({ ok: false, err: "delete_failed" }, 503); }   // same rule as /submit: a bare throw is a CORS-less 500 the client reads as a network error, and an erasure that silently failed is the worst thing here to get wrong
      return json({ ok: true, withdrawn: rid });
    }

    if (url.pathname === "/count") {
      const a = this.sql.exec("SELECT COUNT(*) AS c, COALESCE(SUM(bytes),0) AS b FROM runs").one();
      const b = this.sql.exec("SELECT COUNT(*) AS c, COALESCE(SUM(bytes),0) AS b FROM runs2").one();
      return json({ ok: true, count: a.c + b.c, bytes: a.b + b.b });
    }

    if (url.pathname === "/list") {
      const legacy = [...this.sql.exec("SELECT id,created,meta,bytes FROM runs ORDER BY id DESC LIMIT 2000")].map(r => ({ ...r, kind: "legacy" }));
      const runs = [...this.sql.exec("SELECT rid,created,updated,meta,day,saves,bytes FROM runs2 ORDER BY updated DESC LIMIT 2000")].map(r => ({ ...r, kind: "run" }));
      return json({ ok: true, runs, legacy });
    }

    if (url.pathname === "/delete") {
      const id = Number(url.searchParams.get("id"));
      const rid = url.searchParams.get("rid") || "";
      if (RID.test(rid)) { this.sql.exec("DELETE FROM runs2 WHERE rid=?", rid); return json({ ok: true, deleted: rid }); }
      this.sql.exec("DELETE FROM runs WHERE id=?", id);
      return json({ ok: true, deleted: id });
    }

    if (url.pathname === "/purge") {
      this.sql.exec("DELETE FROM runs");
      this.sql.exec("DELETE FROM runs2");
      return json({ ok: true, purged: true });
    }

    if (url.pathname === "/export") {
      // Streamed, and each body is spliced in as raw text rather than parsed and re-stringified. Accumulating the rows
      // held ~2x the whole archive against a 128 MB DO memory limit, so the only read path OOM'd at a few dozen runs.
      const sql = this.sql, enc = new TextEncoder();
      // Take the KEY LIST synchronously first, then fetch one row per pull. Cloudflare is explicit that a cursor held
      // across an await has no snapshot isolation, so the old generator could interleave pre- and post-write state
      // while still emitting its EOF marker. Ids are tiny, so materialising them costs nothing; each row is then read
      // whole in one synchronous statement, and a row withdrawn mid-export is simply absent rather than half-emitted.
      const legacyIds = sql.exec("SELECT id FROM runs ORDER BY id").toArray().map(r => r.id);
      const rids = sql.exec("SELECT rid FROM runs2 ORDER BY rid").toArray().map(r => r.rid);
      const rows = (function* () {
        for (const id of legacyIds) {
          const r = sql.exec("SELECT id,created,meta,body FROM runs WHERE id=?", id).toArray()[0];
          if (!r) continue;   // deleted since the key list was taken
          let log; try { log = JSON.parse(r.body); } catch { log = r.body; }   // legacy rows predate envelope validation, so they still have to be parsed
          yield JSON.stringify({ kind: "legacy", id: r.id, created: r.created, meta: r.meta, log }) + "\n";
        }
        for (const rid of rids) {
          const r = sql.exec("SELECT rid,created,updated,meta,day,saves,body FROM runs2 WHERE rid=?", rid).toArray()[0];
          if (!r) continue;   // withdrawn mid-export: omit it rather than emit a stale copy
          const head = JSON.stringify({ kind: "run", rid: r.rid, created: r.created, updated: r.updated, meta: r.meta, day: r.day, saves: r.saves });
          // strip raw newlines: JSON.parse accepts them as whitespace, so a pretty-printed submission would otherwise
          // span several physical lines and break NDJSON framing. A newline inside a JSON string is illegal, so this is lossless.
          yield head.slice(0, -1) + ',"env":' + (r.body || "null").replace(/[\n\r]/g, "") + "}\n";
        }
        // completion marker plus the key counts the export was PLANNED from, so a consumer can tell a truncated
        // download from a complete one, and see how many rows vanished under it rather than being told a false total
        yield JSON.stringify({ kind: "eof", planned: legacyIds.length + rids.length }) + "\n";
      })();
      // pull, not start: enqueueing every row up front would hold the whole archive in the stream's queue and OOM exactly
      // as the old array did. pull runs one row per consumer read, so peak memory is one row.
      const stream = new ReadableStream({
        pull(c) { const n = rows.next(); if (n.done) c.close(); else c.enqueue(enc.encode(n.value)); },
        cancel() { rows.return(); }   // client hung up: close the SQL cursors instead of leaving them open until GC
      });
      return new Response(stream, { headers: { "content-type": "application/x-ndjson", ...CORS } });
    }

    return json({ ok: false, err: "not_found" }, 404);
  }
}

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const url = new URL(req.url);

    if (url.pathname === "/submit" || url.pathname === "/withdraw") {
      if (!env.SUBMIT_KEY || url.searchParams.get("k") !== env.SUBMIT_KEY) return json({ ok: false, err: "forbidden" }, 403);   // fail closed
    } else if (["/list", "/export", "/delete", "/purge"].includes(url.pathname)) {
      if (!env.OWNER_KEY || !ctEq(bearer(req), env.OWNER_KEY)) return json({ ok: false, err: "forbidden" }, 403);   // owner key via Authorization header, never in the URL/logs
    } else if (url.pathname !== "/count") {
      return json({ ok: false, err: "not_found" }, 404);
    }

    const stub = env.LOGS.get(env.LOGS.idFromName("collector"));
    return stub.fetch(req);
  },
};
