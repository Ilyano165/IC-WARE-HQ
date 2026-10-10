// Einziger Zugang zum Server: /api/v1, gleiche Herkunft, Sitzungs-Cookie (HttpOnly) — das Skript sieht kein Token.
// Fehler kommen als RFC-9457-Problem und werden als ApiError mit `code` weitergegeben.

export class ApiError extends Error {
  constructor(status, problem) {
    super((problem && (problem.detail || problem.title)) || `Fehler ${status}`);
    this.status = status;
    this.code = (problem && problem.code) || "error";
    this.problem = problem || {};
  }
}

async function antwort(r) {
  if (r.status === 204) return null;
  const typ = r.headers.get("content-type") || "";
  const daten = typ.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const fehler = new ApiError(r.status, typeof daten === "object" ? daten : null);
    // Nur eine wirklich beendete Sitzung meldet ab — ein falsches Passwort/Code (auch 401) ist ein Formularfehler
    if (fehler.code === "authentication_required") window.dispatchEvent(new CustomEvent("ichq:abgemeldet"));
    // Zugang zur Firma weg (z. B. Mitgliedschaft deaktiviert): zurück zur Firmenwahl
    if (fehler.code === "tenant_required") window.dispatchEvent(new CustomEvent("ichq:firma-weg"));
    throw fehler;
  }
  return daten;
}

export async function api(methode, pfad, body) {
  const init = { method: methode, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  return antwort(await fetch(`/api/v1${pfad}`, init));
}

export const get = (p) => api("GET", p);
export const post = (p, b) => api("POST", p, b === undefined ? {} : b);
export const patch = (p, b) => api("PATCH", p, b);
export const put = (p, b) => api("PUT", p, b);
export const del = (p, b) => api("DELETE", p, b);

export async function hochladen(datei) {
  const r = await fetch(`/api/v1/documents?filename=${encodeURIComponent(datei.name)}`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": datei.type || "application/octet-stream", Accept: "application/json" }, body: datei,
  });
  return antwort(r);
}

export function query(params) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    for (const w of Array.isArray(v) ? v : [v]) q.append(k, w);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const FELDER = { title: "Titel", body: "Text", name: "Name", email: "E-Mail", password: "Passwort",
  new_password: "Neues Passwort", current_password: "Aktuelles Passwort", code: "Code", due_date: "Fällig am",
  since: "Seit", until: "Bis", status: "Status", priority: "Priorität", rank: "Rang", description: "Beschreibung",
  display_name: "Name", reason: "Grund", timezone: "Zeitzone", currency: "Währung", language: "Sprache",
  legal_name: "Firmenname (rechtlich)", decision: "Entscheidung", filename: "Dateiname", q: "Suchbegriff" };
const feldname = (loc) => { const f = (loc || []).filter((t) => typeof t === "string" && !["body", "query", "path"].includes(t));
  return FELDER[f[f.length - 1]] || "Eingabe"; };

// Pydantic-Fehlertypen in verständliches Deutsch (der Server-Text ist englisch und technisch)
function pruefung(x) {
  const c = x.ctx || {};
  const t = {
    missing: "fehlt", string_too_short: c.min_length > 1 ? `mindestens ${c.min_length} Zeichen` : "darf nicht leer sein",
    string_too_long: `höchstens ${c.max_length} Zeichen`, too_short: "zu wenige Einträge", too_long: "zu viele Einträge",
    greater_than_equal: `mindestens ${c.ge}`, less_than_equal: `höchstens ${c.le}`, int_parsing: "keine ganze Zahl",
    datetime_from_date_parsing: "kein gültiges Datum", datetime_parsing: "kein gültiger Zeitpunkt",
    date_from_datetime_parsing: "kein gültiges Datum", date_parsing: "kein gültiges Datum", literal_error: "unzulässiger Wert",
    enum: "unzulässiger Wert", string_pattern_mismatch: "ungültiges Format", value_error: "ungültiger Wert",
    extra_forbidden: "unbekanntes Feld", bool_parsing: "kein Ja/Nein-Wert",
  };
  return t[x.type] || "ungültiger Wert";
}

// Lesbare Meldung für Menschen — ohne interne Details
export function meldung(e) {
  if (!(e instanceof ApiError)) return "Verbindung fehlgeschlagen. Bitte erneut versuchen.";
  const texte = {
    permission_denied: "Dafür fehlt die Berechtigung.",
    tenant_paused: "Die Firma ist pausiert — nur Lesen ist möglich.",
    feature_disabled: "Dieses Modul ist für die Firma nicht freigeschaltet.",
    not_found: "Nicht gefunden.",
    last_admin: "Danach gäbe es niemanden mehr mit Verwaltungsrechten.",
  };
  if (e.code === "validation_failed" && e.problem.errors) {
    return e.problem.errors.map((x) => `${feldname(x.loc)}: ${pruefung(x)}`).join(" · ");
  }
  return e.problem.detail || texte[e.code] || e.message;
}
