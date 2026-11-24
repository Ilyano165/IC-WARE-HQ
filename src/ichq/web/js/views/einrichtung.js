// Ersteinrichtung (ADR-021): einmal je Installation, vor jeder Anmeldung. Der Einrichtungscode entsteht nur am
// Server (`hq setup-code`) und steht im Fragment (#/einrichtung?code=…) — er landet nie in einem Serverlog.
// Ergebnis: erste Firma + eigenes Konto als Company Admin UND Betreiber. Danach meldet der Server needed=false.
import { alertBox, ersetze, feld, h, marke } from "../dom.js";
import { ApiError, get, post } from "../api.js";
import { auswahl, eingabe } from "./bausteine.js";
import { assistent, kuerzel, SchrittFehler, SPRACHEN, WAEHRUNGEN, ZEITZONEN, zusammenfassung } from "./assistent.js";

function karte(app, ...inhalt) {
  const box = h("div", { class: "card card--wide" }, marke("HQ"), h("h1", {}, "Installation einrichten"), ...inhalt);
  ersetze(app, h("div", { class: "gate" }, box));
  return box;
}

export async function seite(app, code, fertig) {
  let offen = true;
  try { offen = (await get("/setup")).needed; } catch { /* Server meldet den Fehler beim Abschluss */ }
  if (!offen) {
    karte(app, alertBox("Diese Installation ist bereits eingerichtet. Weitere Firmen legt ein Betreiber nach der Anmeldung unter „Firmen verwalten“ an.", "info"),
      h("button", { class: "btn", type: "button", on: { click: () => fertig() } }, "Zur Anmeldung"));
    return;
  }
  const inhalt = h("div");
  karte(app, h("p", { class: "muted" }, "Einmalig: erste Firma und Ihr Zugang. Danach legen Sie weitere Firmen hier in HQ an — ohne Konsole."), inhalt);
  const d = { code: code || "", timezone: "Europe/Berlin", currency: "EUR", language: "de" };
  assistent(inhalt, [
    { titel: "Code", felder: (x) => [
      h("p", { class: "small muted" }, "Den Code zeigt der Server mit „hq setup-code“ an (Windows: Startmenü „Erste Firma anlegen“). Er gilt 24 Stunden und nur einmal."),
      feld("Einrichtungscode", eingabe("code", x.code, { required: true, minlength: 8, maxlength: 128, autocomplete: "off", spellcheck: false }))] },
    { titel: "Firma", felder: (x) => {
      const slug = eingabe("slug", x.slug, { required: true, minlength: 3, maxlength: 48, pattern: "[a-z0-9][a-z0-9\\-]{1,46}[a-z0-9]" });
      const name = eingabe("name", x.name, { required: true, maxlength: 120, autocomplete: "organization",
        on: { input: () => { if (!slug.dataset.selbst) slug.value = kuerzel(name.value); } } });
      slug.addEventListener("input", () => { slug.dataset.selbst = "1"; });
      if (x.slug) slug.dataset.selbst = "1";
      return [feld("Name der Firma", name), feld("Rechtlicher Name (optional)", eingabe("legal_name", x.legal_name, { maxlength: 200 }), "z. B. „Müller Dach GmbH“ — erscheint später auf Rechnungen."),
        feld("Kürzel", slug, "Kleinbuchstaben, Ziffern, Bindestrich. Lässt sich später nicht ändern."),
        h("div", { class: "grid2" }, feld("Zeitzone", auswahl("timezone", ZEITZONEN, x.timezone)), feld("Währung", auswahl("currency", WAEHRUNGEN, x.currency)))];
    } },
    { titel: "Ihr Zugang", felder: (x) => [
      feld("Ihr Name", eingabe("admin_name", x.admin_name, { required: true, maxlength: 120, autocomplete: "name" })),
      feld("E-Mail (Anmeldename)", eingabe("email", x.email, { type: "email", required: true, maxlength: 254, autocomplete: "email" })),
      feld("Passwort", eingabe("password", x.password, { type: "password", required: true, minlength: 12, maxlength: 512, autocomplete: "new-password" }),
        "Mindestens 12 Zeichen; keine gängigen Passwörter. Danach am besten 2FA unter „Konto & Sicherheit“ einschalten."),
      feld("Passwort wiederholen", eingabe("password2", "", { type: "password", required: true, autocomplete: "new-password" }))],
    pruefe: async (x) => { if (x.password !== x.password2) throw new SchrittFehler("Die Passwörter stimmen nicht überein.", 2); } },
    { titel: "Prüfen", knopf: "Einrichten", felder: (x) => [zusammenfassung([["Firma", x.name], ["Rechtlicher Name", x.legal_name],
      ["Kürzel", x.slug], ["Zeitzone", ZEITZONEN[x.timezone]], ["Währung", WAEHRUNGEN[x.currency]], ["Sprache", SPRACHEN[x.language]],
      ["Administrator", `${x.admin_name} <${x.email}>`]]),
    h("p", { class: "small muted" }, "Ihr Konto wird Administrator dieser Firma und Betreiber der Installation (darf Firmen anlegen und verwalten).")] },
  ], async (x) => {
    try {
      await post("/setup", { code: x.code, email: x.email, name: x.admin_name, password: x.password,
        company: { name: x.name, slug: x.slug, legal_name: x.legal_name || null, timezone: x.timezone, currency: x.currency, language: x.language } });
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) throw new SchrittFehler("Einrichtungscode ungültig, abgelaufen oder schon benutzt. Am Server mit „hq setup-code“ einen neuen ausstellen.", 0);
      if (e instanceof ApiError && e.status === 409) throw new SchrittFehler(e.message.replace(/^slug/, "Kürzel"), 1);
      if (e instanceof ApiError && /Passwort/.test(e.message)) throw new SchrittFehler(e.message, 2);
      if (e instanceof ApiError && /Kürzel|slug|Zeitzone|timezone/i.test(e.message)) throw new SchrittFehler(e.message.replace(/^slug/, "Kürzel"), 1);
      throw e;
    }
    history.replaceState(null, "", "/app/#/");
    karte(app, alertBox(`Eingerichtet. Firma „${x.name}“ ist aktiv.`, "ok"),
      h("p", {}, `Melden Sie sich jetzt mit ${x.email} an.`),
      h("button", { class: "btn", type: "button", on: { click: () => fertig() } }, "Zur Anmeldung"));
  }, d);
}
