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
};
const MAX_BODY = 800 * 1024;              // 800 KB/run row (SQLite row limit is 2 MB); caps spam blast radius
const DB_CUTOFF = 4 * 1024 * 1024 * 1024; // stop accepting NEW runs past 4 GB (free tier is 5 GB account-wide)
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
  }

  dbSize() { try { return this.sql.databaseSize || 0; } catch (_) { return 0; } }

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
      const exists = this.sql.exec("SELECT 1 FROM runs2 WHERE rid=?", rid).toArray().length > 0;
      if (!exists && this.dbSize() > DB_CUTOFF) return json({ ok: false, err: "archive_full" }, 507);
      this.sql.exec(
        `INSERT INTO runs2(rid,created,updated,ua,meta,day,saves,bytes,body)
         VALUES (?,?,?,?,?,?,1,?,?)
         ON CONFLICT(rid) DO UPDATE SET
           updated=excluded.updated, meta=excluded.meta, day=excluded.day,
           saves=runs2.saves+1, bytes=excluded.bytes, body=excluded.body
         WHERE excluded.day >= runs2.day`,
        rid, now, now, ua, meta, day, bytes, body);
      const row = this.sql.exec("SELECT day,saves FROM runs2 WHERE rid=?", rid).toArray()[0] || {};
      return json({ ok: true, day: row.day, saves: row.saves });
    }

    if (url.pathname === "/withdraw" && req.method === "POST") {
      const rid = url.searchParams.get("rid") || "";
      if (!RID.test(rid)) return json({ ok: false, err: "bad_rid" }, 400);
      this.sql.exec("DELETE FROM runs2 WHERE rid=?", rid);   // capability-scoped: only the holder of this rid can erase this run
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
      const out = [];
      for (const r of this.sql.exec("SELECT id,created,meta,body FROM runs ORDER BY id")) {
        let log; try { log = JSON.parse(r.body); } catch { log = r.body; }
        out.push(JSON.stringify({ kind: "legacy", id: r.id, created: r.created, meta: r.meta, log }));
      }
      for (const r of this.sql.exec("SELECT rid,created,updated,meta,day,saves,body FROM runs2 ORDER BY updated")) {
        let env; try { env = JSON.parse(r.body); } catch { env = r.body; }
        out.push(JSON.stringify({ kind: "run", rid: r.rid, created: r.created, updated: r.updated, meta: r.meta, day: r.day, saves: r.saves, env }));
      }
      return new Response(out.join("\n"), { headers: { "content-type": "application/x-ndjson", ...CORS } });
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
