// Konto & Sicherheit (M2): Passwort ändern, 2FA einrichten/ausschalten, Recovery-Codes, überall abmelden, Firma verlassen.
import { alertBox, dialog, ersetze, feld, h, toast } from "../dom.js";
import { get, meldung, post } from "../api.js";
import { state } from "../state.js";

const pw = (name, label, auto = "current-password", min = 1) => feld(label, h("input", { name, type: "password", required: true, autocomplete: auto, minlength: min }));
const code = () => feld("Code aus der App", h("input", { name: "code", required: true, inputmode: "numeric", autocomplete: "one-time-code", minlength: 6, maxlength: 16 }));

function codesAnzeigen(codes) {
  return h("div", { class: "stack" }, alertBox("Recovery-Codes jetzt sicher ablegen — sie werden nur dieses eine Mal angezeigt.", "info"),
    h("div", { class: "codes" }, codes.map((c) => h("span", { class: "code" }, c))));
}

export async function ansicht(el) {
  const s = await get("/auth/session");
  const ausgabe = h("div");
  const neu = () => ansicht(el);
  const sende = async (fn) => { try { await fn(); } catch (e) { ersetze(ausgabe, alertBox(meldung(e))); } };

  const passwort = h("form", { class: "stack" }, pw("current_password", "Aktuelles Passwort"),
    pw("new_password", "Neues Passwort", "new-password", 12), h("p", { class: "muted small" }, "Mindestens 12 Zeichen. Andere Sitzungen werden beendet."),
    h("button", { class: "btn", type: "submit" }, "Passwort ändern"));
  passwort.addEventListener("submit", (e) => { e.preventDefault(); sende(async () => {
    const d = Object.fromEntries(new FormData(passwort).entries());
    await post("/auth/password", d);
    passwort.reset();
    toast("Passwort geändert.");
  }); });

  const zweiFaktor = h("div", { class: "stack" });
  if (s.user.totp_enabled) {
    zweiFaktor.append(h("p", {}, h("span", { class: "tag" }, "aktiv"), " Anmeldung mit zweitem Faktor."),
      h("div", { class: "row" },
        h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
          const d = await dialog("Neue Recovery-Codes", [pw("password", "Passwort"), code()], "Erzeugen");
          if (d) sende(async () => { const r = await post("/auth/2fa/recovery-codes", d); ersetze(ausgabe, codesAnzeigen(r.recovery_codes)); });
        } } }, "Neue Recovery-Codes"),
        h("button", { class: "btn btn--danger btn--sm", type: "button", on: { click: async () => {
          const d = await dialog("2FA ausschalten", [pw("password", "Passwort"), code()], "Ausschalten", true);
          if (d) sende(async () => { await post("/auth/2fa/disable", d); toast("2FA ausgeschaltet."); neu(); });
        } } }, "Ausschalten")));
  } else {
    zweiFaktor.append(h("p", { class: "muted" }, "Empfohlen: zweiter Faktor per Authenticator-App (TOTP)."),
      h("button", { class: "btn btn--sm", type: "button", on: { click: async () => {
        const d = await dialog("2FA einrichten", pw("password", "Passwort"), "Weiter");
        if (!d) return;
        sende(async () => {
          const r = await post("/auth/2fa/setup", d);
          const bestaetigen = h("form", { class: "stack" }, alertBox("Schlüssel in der Authenticator-App eintragen (oder den Link auf dem Handy öffnen), dann den ersten Code eingeben.", "info"),
            feld("Schlüssel", h("input", { value: r.secret, readonly: true, class: "code" })),
            h("p", { class: "small" }, h("a", { href: r.otpauth_uri }, "In Authenticator-App öffnen")), code(),
            h("button", { class: "btn", type: "submit" }, "Aktivieren"));
          bestaetigen.addEventListener("submit", (e) => { e.preventDefault(); sende(async () => {
            const x = await post("/auth/2fa/enable", { code: new FormData(bestaetigen).get("code").replace(/\s+/g, "") });
            ersetze(ausgabe, alertBox("2FA ist aktiv.", "ok"), codesAnzeigen(x.recovery_codes));
            toast("2FA aktiviert.");
          }); });
          ersetze(ausgabe, bestaetigen);
        });
      } } }, "Einrichten"));
  }

  const sitzungen = h("div", { class: "row" },
    h("button", { class: "btn btn--ghost btn--sm", type: "button", on: { click: async () => {
      if (await dialog("Überall abmelden", h("p", {}, "Beendet alle Sitzungen dieses Kontos — auch diese."), "Abmelden", true)) {
        sende(async () => { await post("/auth/logout-all"); location.reload(); });
      }
    } } }, "Überall abmelden"),
    h("button", { class: "btn btn--danger btn--sm", type: "button", on: { click: async () => {
      if (await dialog("Firma verlassen", h("p", {}, `Du verlierst sofort den Zugang zu ${state.firma || "dieser Firma"}.`), "Verlassen", true)) {
        sende(async () => { await post("/membership/leave"); location.reload(); });
      }
    } } }, "Firma verlassen"));

  ersetze(el, h("div", { class: "pagehead" }, h("div", {}, h("h1", {}, "Konto & Sicherheit"), h("p", {}, `${s.user.display_name} · ${s.user.email}`))),
    ausgabe, h("div", { class: "grid2" }, h("section", { class: "card" }, h("h2", {}, "Passwort"), passwort),
      h("section", { class: "card" }, h("h2", {}, "Zwei-Faktor-Anmeldung"), zweiFaktor)),
    h("section", { class: "card" }, h("h2", {}, "Sitzungen und Mitgliedschaft"), sitzungen));
}
