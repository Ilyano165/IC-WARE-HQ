// Anmeldung (M2): Login → ggf. 2FA → Firmenwahl. Einladung annehmen und Passwort neu setzen (M3/M2) über Links
// mit Token im Fragment. Fehlermeldungen kommen vom Server (verraten nicht, ob ein Konto existiert).
import { alertBox, ersetze, feld, h, marke } from "../dom.js";
import { ApiError, get, meldung, post } from "../api.js";

function karte(app, titel, ...inhalt) {
  return ersetze(app, h("div", { class: "gate" }, h("div", { class: "card" }, marke("HQ"), h("h1", {}, titel), ...inhalt)));
}

function formular(onSubmit, felder, knopf) {
  const fehler = h("div");
  const button = h("button", { class: "btn btn--block", type: "submit" }, knopf);
  const form = h("form", { class: "stack", novalidate: false }, fehler, felder, button);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!form.reportValidity()) return;
    button.disabled = true;
    ersetze(fehler);
    try {
      await onSubmit(Object.fromEntries(new FormData(form).entries()));
    } catch (err) {
      ersetze(fehler, alertBox(meldung(err)));
    } finally {
      button.disabled = false;
    }
  });
  return form;
}

const eingabe = (name, typ, extra = {}) => h("input", { name, type: typ, required: true, ...extra });

export function login(app, weiter) {
  const anmelden = formular(async (d) => {
    const r = await post("/auth/login", { login: d.login, password: d.password });
    if (r.status === "mfa_required") mfa(app, weiter);
    else weiter();
  }, [feld("E-Mail oder Benutzername", eingabe("login", "text", { autocomplete: "username", autofocus: true })),
    feld("Passwort", eingabe("password", "password", { autocomplete: "current-password" }))], "Anmelden");
  karte(app, "Anmelden", h("p", { class: "muted" }, "Willkommen zurück."), anmelden,
    h("p", { class: "small" }, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); vergessen(app, weiter); } } },
      "Passwort vergessen?")));
}

function mfa(app, weiter) {
  karte(app, "Zwei-Faktor-Code", h("p", { class: "muted" }, "Code aus der Authenticator-App oder ein Recovery-Code."),
    formular(async (d) => { await post("/auth/mfa", { code: d.code.replace(/\s+/g, "") }); weiter(); },
      [feld("Code", eingabe("code", "text", { inputmode: "numeric", autocomplete: "one-time-code", autofocus: true,
        minlength: 6, maxlength: 16 }))], "Bestätigen"));
}

function vergessen(app, weiter) {
  const fertig = h("div");
  karte(app, "Passwort vergessen", fertig,
    formular(async (d) => {
      await post("/auth/password-reset/request", { login: d.login });
      ersetze(fertig, alertBox("Wenn es das Konto gibt, ist eine E-Mail mit einem Link unterwegs (30 Minuten gültig).", "ok"));
    }, [feld("E-Mail oder Benutzername", eingabe("login", "text", { autocomplete: "username" }))], "Link anfordern"),
    h("p", { class: "small" }, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); login(app, weiter); } } }, "Zur Anmeldung")));
}

export function firmenwahl(app, sitzung, weiter, wechsel = false) {
  const aktiv = sitzung.memberships.filter((m) => m.membership_status === "active"
    && ["active", "paused"].includes(m.tenant_status));
  const waehle = async (id) => { await post("/auth/tenant", { tenant_id: id }); location.hash = "#/"; weiter(); };
  if (aktiv.length === 1 && !wechsel) { waehle(aktiv[0].tenant_id).catch((e) => karte(app, "Firma", alertBox(meldung(e)))); return; }
  if (!aktiv.length) {
    karte(app, "Keine Firma", h("p", { class: "muted" }, "Dieses Konto gehört noch zu keiner aktiven Firma. Eine Einladung gibt Zugang."),
      h("button", { class: "btn btn--ghost", type: "button", on: { click: async () => { await post("/auth/logout"); weiter(); } } }, "Abmelden"));
    return;
  }
  const fehler = h("div");
  karte(app, "Firma wählen", fehler, h("div", { class: "list" }, aktiv.map((m) =>
    h("button", { class: "item", type: "button", on: { click: () => waehle(m.tenant_id).catch((e) => ersetze(fehler, alertBox(meldung(e)))) } },
      h("span", {}, h("b", {}, m.name), h("div", { class: "meta" }, m.slug)),
      m.tenant_status === "paused" ? h("span", { class: "tag tag--warn" }, "pausiert") : h("span", { class: "tag" }, "öffnen")))));
}

export function oeffentlich(app, art, token, fertig) {
  if (art === "passwort-neu") {
    karte(app, "Neues Passwort", h("p", { class: "muted" }, "Mindestens 12 Zeichen. Alle Sitzungen werden beendet."),
      formular(async (d) => {
        await post("/auth/password-reset/confirm", { token, new_password: d.password });
        karte(app, "Passwort gesetzt", alertBox("Das Passwort ist geändert. Bitte neu anmelden.", "ok"),
          h("button", { class: "btn btn--block", type: "button", on: { click: fertig } }, "Zur Anmeldung"));
      }, [feld("Neues Passwort", eingabe("password", "password", { autocomplete: "new-password", minlength: 12 }))], "Speichern"));
    return;
  }
  const bestehend = async () => {
    try {
      await get("/auth/session");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        login(app, () => oeffentlich(app, art, token, fertig));
        return;
      }
      throw e;
    }
    await post("/invitations/accept-existing", { token });
    fertig();
  };
  karte(app, "Einladung annehmen",
    h("p", { class: "muted" }, "Neues Konto anlegen — oder mit einem bestehenden Konto annehmen."),
    formular(async (d) => {
      try {
        await post("/invitations/accept", { token, display_name: d.display_name, password: d.password });
      } catch (e) {
        if (e instanceof ApiError && e.code === "account_exists") { await bestehend(); return; }
        throw e;
      }
      karte(app, "Willkommen", alertBox("Das Konto ist angelegt. Bitte anmelden.", "ok"),
        h("button", { class: "btn btn--block", type: "button", on: { click: fertig } }, "Zur Anmeldung"));
    }, [feld("Name", eingabe("display_name", "text", { autocomplete: "name", maxlength: 120 })),
      feld("Passwort", eingabe("password", "password", { autocomplete: "new-password", minlength: 12 }), "Mindestens 12 Zeichen.")],
    "Konto anlegen"),
    h("p", { class: "small" }, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); bestehend().catch((x) => karte(app, "Einladung", alertBox(meldung(x)))); } } },
      "Ich habe schon ein Konto")));
}
