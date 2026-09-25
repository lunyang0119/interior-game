/**
 * Google Apps Script web app for the shared currency pool.
 *
 * Sheet layout (tab "Characters"): B = nickname (= game ID), O = earned currency,
 * R = game ID written by the server when that person registers.
 *
 * Deploy: open the Discord_Bot spreadsheet → Extensions → Apps Script → paste →
 *   Deploy → New deployment → type "Web app", Execute as: Me, Who has access: Anyone.
 *   After EVERY code change: Deploy → Manage deployments → edit → New version → Deploy.
 *   Copy the /exec URL into server/.env as SHEET_URL.
 *
 * GET  → {"members":[{"id":"닉네임","name":"닉네임","earned":1500}, ...]}
 * POST {"action":"register","id":"닉네임","secret":"..."}
 *      → exact match on B or R, else the single row whose B contains the text; writes id to R.
 *        Not found → appends a new row (B and R = id). Several partial matches → {"ok":false,"error":"ambiguous"}.
 *        Row already registered under another id → {"ok":false,"error":"taken"}.
 *      → {"ok":true,"id":"닉네임","name":"시트의 B열 값","created":false,"earned":1500}
 */

const SHEET_NAME = "Characters";
const NAME_COL = 2;    // B: nickname
const EARNED_COL = 15; // O: currency
const ID_COL = 18;     // R: game id
const HEADER_ROWS = 1;
const SECRET = "";     // optional: same value as SHEET_SECRET in server/.env. Empty = no check.

function _sheet() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function _members(sheet) {
  const rows = sheet.getDataRange().getValues().slice(HEADER_ROWS);
  const members = [];
  rows.forEach(function (row) {
    const name = String(row[NAME_COL - 1] || "").trim();
    const gid = String(row[ID_COL - 1] || "").trim();
    const id = gid || name;
    if (!id) return;
    members.push({ id: id, name: name, earned: Math.floor(Number(row[EARNED_COL - 1]) || 0) });
  });
  return members;
}

function doGet() {
  return _json({ members: _members(_sheet()) });
}

function _norm(s) {
  return String(s || "").replace(/\s+/g, "").toLowerCase();
}

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return _json({ ok: false, error: "bad_json" });
  }
  if (SECRET && body.secret !== SECRET) return _json({ ok: false, error: "forbidden" });
  if (body.action !== "register") return _json({ ok: false, error: "unknown_action" });
  const id = String(body.id || "").trim();
  if (!id) return _json({ ok: false, error: "empty_id" });
  const key = _norm(id);

  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sheet = _sheet();
    const values = sheet.getDataRange().getValues();
    // 1) exact match on B (nickname) or R (already-registered game id)
    // 2) otherwise a single row whose nickname CONTAINS the typed text ("게쉬틴" → "게쉬틴안나 보니것")
    let exact = -1;
    const partial = [];
    for (let r = HEADER_ROWS; r < values.length; r++) {
      const name = _norm(values[r][NAME_COL - 1]);
      const gid = _norm(values[r][ID_COL - 1]);
      if (gid === key || name === key) { exact = r; break; }
      if (name && name.indexOf(key) !== -1) partial.push(r);
    }
    let r = exact;
    if (r < 0) {
      if (partial.length > 1) {
        return _json({ ok: false, error: "ambiguous", candidates: partial.map(function (i) { return String(values[i][NAME_COL - 1]).trim(); }) });
      }
      if (partial.length === 1) r = partial[0];
    }
    if (r >= 0) {
      const gid = String(values[r][ID_COL - 1] || "").trim();
      if (gid && _norm(gid) !== key) return _json({ ok: false, error: "taken", name: String(values[r][NAME_COL - 1]).trim() });
      if (gid !== id) sheet.getRange(r + 1, ID_COL).setValue(id);
      return _json({ ok: true, id: id, name: String(values[r][NAME_COL - 1]).trim(), created: false,
                     earned: Math.floor(Number(values[r][EARNED_COL - 1]) || 0) });
    }
    const row = new Array(Math.max(sheet.getLastColumn(), ID_COL)).fill("");
    row[NAME_COL - 1] = id;
    row[ID_COL - 1] = id;
    sheet.appendRow(row);
    return _json({ ok: true, id: id, name: id, created: true, earned: 0 });
  } finally {
    lock.releaseLock();
  }
}
