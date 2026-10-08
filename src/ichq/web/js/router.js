// Routing über das Fragment (#/aufgaben/…): Der Server kennt keine App-Pfade; Tokens im Fragment landen nie im Serverlog.

const routen = [];

export function route(muster, ansicht, recht) {
  const namen = [];
  const re = new RegExp(`^${muster.replace(/:([a-z]+)/g, (_, n) => { namen.push(n); return "([^/?]+)"; })}$`);
  routen.push({ re, namen, ansicht, recht, muster });
}

export function aktuell() {
  const roh = location.hash.replace(/^#/, "") || "/";
  const [pfad, qs] = roh.split("?");
  return { pfad, query: new URLSearchParams(qs || "") };
}

export function finde(pfad) {
  for (const r of routen) {
    const m = r.re.exec(pfad);
    if (m) return { ...r, params: Object.fromEntries(r.namen.map((n, i) => [n, decodeURIComponent(m[i + 1])])) };
  }
  return null;
}

export function gehe(pfad) {
  if (location.hash === `#${pfad}`) window.dispatchEvent(new HashChangeEvent("hashchange"));
  else location.hash = pfad;
}
