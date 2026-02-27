/**
 * Agenda Mussali — Google Apps Script
 * 
 * Features:
 *  1. onEdit: blocks overwriting a filled cell (only sheet owner can edit)
 *  2. onOpen: auto-hides rows where the date has already passed
 * 
 * HOW TO INSTALL:
 *  1. Open the Google Sheet
 *  2. Click Extensions → Apps Script
 *  3. Delete everything in the editor and paste this entire file
 *  4. Click Save (💾 icon)
 *  5. Click Run → select "configurarHoja" → click Run
 *  6. Google will ask for permission — click "Review permissions" → Allow
 *  7. Done! The script will now run automatically.
 */

// ─── Config ──────────────────────────────────────────────────────────────────

// Column index of the date column (A = 1) in each bookable sheet
const DATE_COL = 1;

// Row where dates start (after title + subtitle + header rows)
const DATA_START_ROW = 4;

// Sheet names to protect and auto-hide (must match exactly)
const BOOKABLE_SHEETS = [
  "1 - Emilio 📚",
  "2 - Baño Bebé 🛁",
  "3 - Visitas 🏠"
];

// Columns that contain bookable name cells in each sheet
// (A=1, B=2, C=3, D=4, E=5, F=6)
const BOOKABLE_COLS = {
  "1 - Emilio 📚":  [3, 4, 5, 6],  // C, D, E, F
  "2 - Baño Bebé 🛁": [3],          // C
  "3 - Visitas 🏠":  [3, 4, 5]      // C, D, E
};

// ─── 1. Block overwriting filled cells ───────────────────────────────────────

function onEdit(e) {
  const sheet = e.range.getSheet();
  const sheetName = sheet.getName();

  // Only act on bookable sheets
  if (!BOOKABLE_SHEETS.includes(sheetName)) return;

  const col = e.range.getColumn();
  const row = e.range.getRow();

  // Only act on bookable columns
  const bookableCols = BOOKABLE_COLS[sheetName] || [];
  if (!bookableCols.includes(col)) return;

  // Only act on data rows (not headers)
  if (row < DATA_START_ROW) return;

  // If the cell previously had a value (oldValue), someone is trying to overwrite it
  const oldValue = e.oldValue;
  if (oldValue !== undefined && oldValue !== "" && oldValue !== null) {
    // Check if the current user is the owner (Edu)
    const owner = e.source.getOwner().getEmail();
    const user  = Session.getActiveUser().getEmail();

    if (user !== owner) {
      // Revert the change
      e.range.setValue(oldValue);
      SpreadsheetApp.getUi().alert(
        "⚠️ Esta celda ya está reservada.\n\nSi necesitas cambiar tu reserva, contacta a Edu directamente por WhatsApp."
      );
      return;
    }
  }
}

// ─── 2. Auto-hide past rows on open ──────────────────────────────────────────

function onOpen() {
  ocultarDiasPasados();
}

function ocultarDiasPasados() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const today = new Date();
  today.setHours(0, 0, 0, 0);  // normalize to midnight

  BOOKABLE_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;

    const lastRow = sheet.getLastRow();
    if (lastRow < DATA_START_ROW) return;

    for (let r = DATA_START_ROW; r <= lastRow; r++) {
      const cellVal = sheet.getRange(r, DATE_COL).getValue();

      // Skip empty or non-date cells
      if (!cellVal) continue;

      // The date cells have text like "1 Mar", "15 Mar" etc.
      // We parse them by appending the year
      let rowDate;
      if (cellVal instanceof Date) {
        rowDate = new Date(cellVal);
      } else {
        // Parse text date like "1 Mar"
        rowDate = new Date(cellVal + " 2026");
      }

      if (isNaN(rowDate.getTime())) continue;
      rowDate.setHours(0, 0, 0, 0);

      // Hide row if the date is strictly before today
      if (rowDate < today) {
        sheet.hideRows(r);
      } else {
        sheet.showRows(r);
      }
    }
  });
}

// ─── 3. Manual trigger: show ALL rows (run this if you want to see everything) ──

function mostrarTodosFechas() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  BOOKABLE_SHEETS.forEach(sheetName => {
    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) return;
    const lastRow = sheet.getLastRow();
    if (lastRow >= DATA_START_ROW) {
      sheet.showRows(DATA_START_ROW, lastRow - DATA_START_ROW + 1);
    }
  });
  SpreadsheetApp.getUi().alert("✅ Todas las filas están visibles ahora.");
}

// ─── 4. Initial setup (run once after pasting this script) ───────────────────

function configurarHoja() {
  ocultarDiasPasados();
  SpreadsheetApp.getUi().alert(
    "✅ ¡Listo! El script está activo.\n\n" +
    "• Las fechas pasadas se ocultan automáticamente al abrir.\n" +
    "• Las celdas reservadas no pueden ser editadas por otros.\n" +
    "• Solo tú (el dueño) puedes editar celdas ya reservadas."
  );
}
