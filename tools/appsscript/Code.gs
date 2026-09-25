/**
 * Google Apps Script web app for the shared currency pool.
 *
 * Deploy: Extensions → Apps Script → paste → Deploy → New deployment → Web app,
 *   Execute as: Me, Who has access: Anyone. Copy the /exec URL into server/.env as SHEET_URL.
 *
 * Response: {"members":[{"id":"lun","earned":1500}, ...]}
 * The server sums every member's `earned` into one shared pool.
 */

const SHEET_NAME = "Sheet1";  // tab name
const ID_COL = 1;             // A = 1
const EARNED_COL = 2;         // B = 2
const HEADER_ROWS = 1;

function doGet() {
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  const rows = sheet.getDataRange().getValues().slice(HEADER_ROWS);
  const members = [];
  for (const row of rows) {
    const id = String(row[ID_COL - 1] || "").trim();
    if (!id) continue;
    const earned = Math.floor(Number(row[EARNED_COL - 1]) || 0);
    members.push({ id: id, earned: earned });
  }
  return ContentService
    .createTextOutput(JSON.stringify({ members: members }))
    .setMimeType(ContentService.MimeType.JSON);
}
