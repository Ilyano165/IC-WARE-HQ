// Sitzungszustand im Speicher (nichts in localStorage — Rechte kommen bei jedem Laden frisch vom Server).
// Die Oberfläche blendet nur aus; ENTSCHIEDEN wird immer serverseitig.

export const state = { sitzung: null, me: null, rechte: new Set(), firma: null };

export function darf(...rechte) {
  return rechte.every((r) => state.rechte.has(r));
}

export function setzeMe(me) {
  state.me = me;
  state.rechte = new Set(me ? me.permissions : []);
}
