/*
 * Swiss Ice Hockey (National League) – Lovelace cards
 *   custom:swiss-hockey-next-game   next game of the favourite club
 *   custom:swiss-hockey-standings   league table
 *   custom:swiss-hockey-club        one club (also used as pop-up)
 * Data: websocket "swiss_hockey/subscribe" (one shared subscription).
 * No external dependencies. MIT License.
 */

const VERSION = "0.1.3";

/* ------------------------------------------------------------------ texts */

const TEXT = {
  en: {
    loading: "Loading National League data…",
    notSetUp: "Swiss Ice Hockey is not set up. Add the integration under Settings → Devices & services.",
    noGame: "No upcoming game",
    live: "LIVE",
    final: "FINAL",
    pts: "pts",
    standings: "Standings",
    gp: "GP",
    diff: "+/-",
    points: "PTS",
    lastResults: "Last results",
    nextGames: "Next games",
    none: "None",
    unknownTeam: "Unknown club",
    home: "Home",
    away: "Away",
    rank: "Rank",
    form: "Form",
    nextGame: "Next game",
    club: "Club",
    source: "Data: data.sihf.ch",
    today: "Today",
    tomorrow: "Tomorrow",
    favouriteClub: "Favourite club",
    clubHelp: "Leave on 'Favourite club' to follow the club chosen when setting up the integration.",
    title: "Title",
    compact: "Compact (abbreviations only)",
  },
  de: {
    loading: "Lade Daten der National League…",
    notSetUp: "Swiss Ice Hockey ist nicht eingerichtet. Integration unter Einstellungen → Geräte & Dienste hinzufügen.",
    noGame: "Kein bevorstehendes Spiel",
    live: "LIVE",
    final: "FINAL",
    pts: "P",
    standings: "Rangliste",
    gp: "Sp",
    diff: "+/-",
    points: "P",
    lastResults: "Letzte Resultate",
    nextGames: "Nächste Spiele",
    none: "Keine",
    unknownTeam: "Unbekannter Verein",
    home: "Heim",
    away: "Auswärts",
    rank: "Rang",
    form: "Form",
    nextGame: "Nächstes Spiel",
    club: "Verein",
    source: "Daten: data.sihf.ch",
    today: "Heute",
    tomorrow: "Morgen",
    favouriteClub: "Lieblingsverein",
    clubHelp: "Auf 'Lieblingsverein' lassen, dann gilt der Verein aus der Einrichtung der Integration.",
    title: "Titel",
    compact: "Kompakt (nur Kürzel)",
  },
};

const lang = (hass) => ((hass && (hass.locale?.language || hass.language)) || "en").slice(0, 2);
const t = (hass, key) => (TEXT[lang(hass)] || TEXT.en)[key] ?? TEXT.en[key] ?? key;
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/* ------------------------------------------------------------ data store */

const store = {
  data: null,
  error: null,
  listeners: new Set(),
  unsub: null,
  pending: false,
  conn: null,
  timer: null,

  attach(hass, listener) {
    this.listeners.add(listener);
    if (this.data || this.error) listener();
    this.connect(hass);
  },

  detach(listener) {
    this.listeners.delete(listener);
  },

  async connect(hass, force = false) {
    if (!hass?.connection) return;
    if (!force && this.conn === hass.connection && (this.unsub || this.pending)) return;
    if (this.conn !== hass.connection) {
      this.conn = hass.connection;
      // After a restart of Home Assistant: subscribe again once it is back.
      hass.connection.addEventListener("ready", () => this.retry(hass, 3000));
    }
    if (this.unsub) {
      const old = this.unsub;
      this.unsub = null;
      old.then((fn) => fn()).catch(() => {});
    }
    this.pending = true;
    const sub = hass.connection.subscribeMessage(
      (msg) => {
        this.data = msg;
        this.error = null;
        this.notify();
      },
      { type: "swiss_hockey/subscribe" },
      { resubscribe: false },
    );
    sub
      .then(() => {
        this.pending = false;
        this.unsub = sub;
      })
      .catch((err) => {
        this.pending = false;
        // Integration not (yet) loaded, e.g. while Home Assistant is starting: try again.
        this.error = this.data ? null : err?.code || "error";
        this.notify();
        this.retry(hass, 10000);
      });
  },

  retry(hass, delay) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.connect(hass, true), delay);
  },

  notify() {
    this.listeners.forEach((fn) => fn());
  },
};

/* ------------------------------------------------------------- helpers */

function teamInfo(data, acr) {
  return (data?.teams && data.teams[acr]) || { name: acr, logo: null };
}

function hue(acr) {
  let h = 0;
  for (const c of String(acr)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function logoHtml(data, acr, size) {
  const info = teamInfo(data, acr);
  const fallback = `<span class="fb" style="width:${size}px;height:${size}px;font-size:${Math.round(size / 3.2)}px;background:hsl(${hue(acr)},45%,38%)">${esc(acr)}</span>`;
  if (!info.logo) return `<span class="logo" style="width:${size}px;height:${size}px">${fallback}</span>`;
  return `<span class="logo" style="width:${size}px;height:${size}px"><img src="${esc(info.logo)}" alt="${esc(acr)}" loading="lazy"><template>${fallback}</template></span>`;
}

// Replace logos that fail to load by the abbreviation circle (no inline handlers).
function wireLogos(root) {
  root.querySelectorAll(".logo img").forEach((img) => {
    const swap = () => {
      const tpl = img.nextElementSibling;
      if (tpl && tpl.tagName === "TEMPLATE") img.replaceWith(tpl.content.cloneNode(true));
    };
    if (img.complete && img.naturalWidth === 0) swap();
    else img.addEventListener("error", swap, { once: true });
  });
}

function tz(hass) {
  return hass?.config?.time_zone || undefined;
}

function fmt(hass, iso, opts) {
  try {
    return new Intl.DateTimeFormat(lang(hass), { timeZone: tz(hass), ...opts }).format(new Date(iso));
  } catch (_e) {
    return new Date(iso).toLocaleString();
  }
}

function dayKey(hass, date) {
  return fmt(hass, date.toISOString(), { year: "numeric", month: "2-digit", day: "2-digit" });
}

function dayLabel(hass, iso) {
  const d = new Date(iso);
  const now = new Date();
  if (dayKey(hass, d) === dayKey(hass, now)) return t(hass, "today");
  if (dayKey(hass, d) === dayKey(hass, new Date(now.getTime() + 86400000))) return t(hass, "tomorrow");
  return fmt(hass, iso, { weekday: "short", day: "numeric", month: "short" });
}

const timeOf = (hass, iso) => fmt(hass, iso, { hour: "2-digit", minute: "2-digit" });
const shortDate = (hass, iso) => fmt(hass, iso, { day: "2-digit", month: "2-digit" });

function teamGames(data, acr) {
  return (data?.games || []).filter((g) => g.home === acr || g.away === acr);
}

const isLive = (g) => g.pct > 0 && g.pct < 100;
const isDone = (g) => g.pct >= 100;

function result(g, acr) {
  if (g.hs == null || g.as == null) return "";
  const mine = g.home === acr ? g.hs : g.as;
  const other = g.home === acr ? g.as : g.hs;
  return mine > other ? "W" : "L";
}

function lastGames(data, acr, n = 5) {
  return teamGames(data, acr).filter(isDone).sort((a, b) => b.start.localeCompare(a.start)).slice(0, n);
}

function nextGames(data, acr, n = 5) {
  return teamGames(data, acr)
    .filter((g) => !isDone(g))
    .sort((a, b) => a.start.localeCompare(b.start))
    .slice(0, n);
}

// Current table position after a club name, e.g. " #5".
function rankHtml(data, acr) {
  const r = standing(data, acr);
  return r ? ` <span class="rk">#${r.rank}</span>` : "";
}

function standing(data, acr) {
  return (data?.standings || []).find((r) => r.team === acr);
}

function formDots(data, acr) {
  return lastGames(data, acr, 5)
    .reverse()
    .map((g) => `<span class="dot ${result(g, acr) === "W" ? "w" : "l"}" title="${esc(g.home)} ${g.hs}:${g.as} ${esc(g.away)}"></span>`)
    .join("");
}

/* ----------------------------------------------------------- shared CSS */

const CSS = `
  :host { display: block; }
  ha-card { padding: 16px; overflow: hidden; }
  .muted { color: var(--secondary-text-color); }
  .small { font-size: 12px; }
  .title { font-size: 16px; font-weight: 500; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .logo { display: inline-flex; align-items: center; justify-content: center; flex: none; }
  .logo img { width: 100%; height: 100%; object-fit: contain; }
  .fb { display: inline-flex; align-items: center; justify-content: center; border-radius: 50%; color: #fff; font-weight: 600; letter-spacing: .02em; }
  .badge { font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 10px; background: var(--secondary-background-color); color: var(--secondary-text-color); white-space: nowrap; }
  .badge.live { background: var(--error-color, #db4437); color: #fff; }
  .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin: 0 2px; }
  .dot.w { background: var(--success-color, #43a047); }
  .dot.l { background: var(--error-color, #db4437); }
  .clickable { cursor: pointer; }
  .msg { padding: 8px 0; color: var(--secondary-text-color); }
  .rows { display: flex; flex-direction: column; }
  .gr { display: grid; grid-template-columns: 72px 20px 26px 1fr auto auto; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--divider-color); font-size: 14px; }
  .gr:last-child { border-bottom: none; }
  .res { font-weight: 600; font-variant-numeric: tabular-nums; }
  .wl { font-size: 11px; font-weight: 700; width: 18px; height: 18px; border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; color: #fff; }
  .wl.w { background: var(--success-color, #43a047); }
  .wl.l { background: var(--error-color, #db4437); }
  .sec { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--secondary-text-color); margin: 16px 0 4px; }
  ha-icon { --mdc-icon-size: 16px; color: var(--secondary-text-color); }
  .nx { display: flex; flex-direction: column; align-items: flex-end; line-height: 1.2; }
  .nx .tv { font-size: 11px; font-weight: 400; color: var(--secondary-text-color); }
  .rk { color: var(--secondary-text-color); font-weight: 400; font-size: .85em; white-space: nowrap; }
`;

/* ------------------------------------------------------------ base card */

// Card editor: club dropdown. Empty = favourite club from the integration setup.
function uiHass() {
  return document.querySelector("home-assistant")?.hass;
}

function clubForm() {
  const hass = uiHass();
  const d = store.data;
  const fav = d?.favourite;
  const favName = fav ? teamInfo(d, fav).name : "";
  const options = [{ value: "", label: `★ ${t(hass, "favouriteClub")}${favName ? ` (${favName})` : ""}` }];
  for (const r of d?.standings || []) {
    options.push({ value: r.team, label: `${teamInfo(d, r.team).name} (${r.team})` });
  }
  return {
    schema: [{ name: "team", selector: { select: { mode: "dropdown", options } } }],
    computeLabel: () => t(hass, "club"),
    computeHelper: () => t(hass, "clubHelp"),
  };
}

class SwissHockeyBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._listener = () => this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first || this._conn !== hass.connection) {
      this._conn = hass.connection;
      store.attach(hass, this._listener);
    }
  }

  setConfig(config) {
    this._config = { ...config };
    if (!this._config.team) delete this._config.team; // empty = favourite club
    this._render();
  }

  connectedCallback() {
    if (this._hass) store.attach(this._hass, this._listener);
  }

  disconnectedCallback() {
    store.detach(this._listener);
  }

  get data() {
    return store.data;
  }

  _status() {
    // "not_loaded": integration installed but not ready yet (e.g. Home Assistant starting) -> keep "loading".
    if (store.error && store.error !== "not_loaded") return `<div class="msg">${esc(t(this._hass, "notSetUp"))}</div>`;
    if (!store.data || !store.data.ready) return `<div class="msg">${esc(t(this._hass, "loading"))}</div>`;
    return null;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const status = this._status();
    this.shadowRoot.innerHTML = `<style>${CSS}${this.css || ""}</style><ha-card>${status ?? this.body()}</ha-card>`;
    if (!status) {
      wireLogos(this.shadowRoot);
      this.bind();
    }
  }

  _clubClicks(root = this.shadowRoot) {
    root.querySelectorAll("[data-club]").forEach((el) =>
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openClubDialog(this._hass, el.dataset.club);
      }),
    );
  }

  bind() {
    this._clubClicks();
  }

  team() {
    return (this._config.team || this.data?.favourite || "").toUpperCase();
  }
}

/* ------------------------------------------------------- next-game card */

class SwissHockeyNextGameCard extends SwissHockeyBase {
  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return clubForm();
  }

  getCardSize() {
    return 3;
  }

  get css() {
    return `
      .match { display: grid; grid-template-columns: 1fr auto 1fr; align-items: start; gap: 8px; }
      .mid { align-self: center; }
      .side { display: flex; flex-direction: column; align-items: center; gap: 6px; text-align: center; min-width: 0; }
      .name { font-size: 14px; font-weight: 500; line-height: 1.25; max-width: 100%; overflow-wrap: anywhere; }
      .mid { text-align: center; min-width: 96px; }
      .big { font-size: 30px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
      .when { font-size: 14px; color: var(--secondary-text-color); }
      .foot { display: flex; justify-content: space-between; align-items: center; margin-top: 14px; gap: 8px; }
      .fav .name { color: var(--primary-color); }
    `;
  }

  _game() {
    const acr = this.team();
    const games = teamGames(this.data, acr);
    const live = games.find(isLive);
    if (live) return { game: live, mode: "live" };
    // Like the desk display: show the final score until noon of the next day.
    const last = lastGames(this.data, acr, 1)[0];
    if (last) {
      const start = new Date(last.start);
      const noon = new Date(start);
      noon.setDate(noon.getDate() + 1);
      noon.setHours(12, 0, 0, 0);
      if (Date.now() < noon.getTime()) return { game: last, mode: "final" };
    }
    const next = nextGames(this.data, acr, 1)[0];
    return next ? { game: next, mode: "next" } : null;
  }

  body() {
    const hass = this._hass;
    const acr = this.team();
    const row = standing(this.data, acr);
    const found = this._game();
    const rankBadge = row ? `#${row.rank} · ${row.pts} ${t(hass, "pts")}` : "";
    if (!found) {
      return `<div class="title"><span>${esc(teamInfo(this.data, acr).name)}</span>${rankBadge ? `<span class="badge">${rankBadge}</span>` : ""}</div>
        <div class="msg">${esc(t(hass, "noGame"))}</div>`;
    }
    const { game: g, mode } = found;
    let badge = `<span class="badge">${esc(rankBadge || "National League")}</span>`;
    let mid;
    if (mode === "live") {
      badge = `<span class="badge live">${t(hass, "live")}</span>`;
      mid = `<div class="big">${g.hs ?? 0}:${g.as ?? 0}</div><div class="when">${esc(g.status)}</div>`;
    } else if (mode === "final") {
      badge = `<span class="badge">${t(hass, "final")}${g.dec ? " " + esc(g.dec) : ""}</span>`;
      mid = `<div class="big">${g.hs}:${g.as}</div><div class="when">${esc(dayLabel(hass, g.start))}</div>`;
    } else {
      mid = `<div class="when">${esc(dayLabel(hass, g.start))}</div><div class="big">${esc(timeOf(hass, g.start))}</div>`;
    }
    const side = (team) => `
      <div class="side clickable ${team === acr ? "fav" : ""}" data-club="${esc(team)}">
        ${logoHtml(this.data, team, 56)}
        <div class="name">${esc(teamInfo(this.data, team).name)}${rankHtml(this.data, team)}</div>
      </div>`;
    const tv = (g.tv || []).join(", ");
    return `
      <div class="title"><span>${esc(t(hass, "nextGame"))}</span>${badge}</div>
      <div class="match">${side(g.home)}<div class="mid">${mid}</div>${side(g.away)}</div>
      <div class="foot">
        <span class="small muted">${tv ? `<ha-icon icon="mdi:television-classic"></ha-icon> ${esc(tv)}` : ""}</span>
        <span title="${esc(t(hass, "form"))}">${formDots(this.data, acr)}</span>
      </div>`;
  }
}

/* ------------------------------------------------------- standings card */

class SwissHockeyStandingsCard extends SwissHockeyBase {
  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        { name: "compact", selector: { boolean: {} } },
      ],
      computeLabel: (sch) => t(uiHass(), sch.name),
    };
  }

  getCardSize() {
    return 8;
  }

  get css() {
    return `
      table { width: 100%; border-collapse: collapse; font-size: 14px; font-variant-numeric: tabular-nums; }
      th { font-size: 12px; font-weight: 500; color: var(--secondary-text-color); text-align: right; padding: 0 4px 6px; }
      th.l { text-align: left; }
      td { padding: 5px 4px; text-align: right; white-space: nowrap; }
      td.rk { color: var(--secondary-text-color); width: 22px; }
      td.lg { width: 24px; text-align: center; }
      td.nm { text-align: left; overflow: hidden; text-overflow: ellipsis; max-width: 0; width: 100%; }
      td.pt { font-weight: 600; }
      tr.team { cursor: pointer; }
      tr.team:hover td { background: var(--secondary-background-color); }
      tr.fav td { color: var(--primary-color); font-weight: 600; }
      tr.line td { padding: 0 4px 2px; border-bottom: 1px dashed var(--divider-color); font-size: 10px; line-height: 12px; color: var(--secondary-text-color); text-align: right; }
      tr.line.nolabel td { padding: 0; line-height: 0; }
      .foot { margin-top: 8px; display: flex; justify-content: space-between; }
    `;
  }

  body() {
    const hass = this._hass;
    const d = this.data;
    const fav = d.favourite;
    const compact = !!this._config.compact;
    const lines = new Map((d.lines || []).map((l) => [l.after, l.label]));
    const rows = (d.standings || [])
      .map((r) => {
        const info = teamInfo(d, r.team);
        const diff = r.gf - r.ga;
        let html = `<tr class="team ${r.team === fav ? "fav" : ""}" data-club="${esc(r.team)}">
          <td class="rk">${r.rank}</td>
          <td class="lg">${logoHtml(d, r.team, 20)}</td>
          <td class="nm">${esc(compact ? r.team : info.name)}</td>
          <td>${r.gp}</td><td>${diff > 0 ? "+" : ""}${diff}</td><td class="pt">${r.pts}</td></tr>`;
        if (lines.has(r.rank)) {
          const lbl = lines.get(r.rank);
          html += `<tr class="line ${lbl ? "" : "nolabel"}"><td colspan="6">${esc(lbl)}</td></tr>`;
        }
        return html;
      })
      .join("");
    return `
      <div class="title"><span>${esc(this._config.title || `National League ${d.season || ""}`)}</span><span class="badge">${esc(d.phase || "")}</span></div>
      <table>
        <thead><tr><th class="l" colspan="3">${esc(t(hass, "standings"))}</th><th>${t(hass, "gp")}</th><th>${t(hass, "diff")}</th><th>${t(hass, "points")}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="foot small muted"><span>${esc(t(hass, "source"))}</span></div>`;
  }
}

/* ------------------------------------------------------------ club view */

function clubHtml(hass, data, acr) {
  const info = teamInfo(data, acr);
  if (!data?.teams?.[acr]) return `<div class="msg">${esc(t(hass, "unknownTeam"))}: ${esc(acr)}</div>`;
  const row = standing(data, acr);
  const last = lastGames(data, acr, 5);
  const next = nextGames(data, acr, 5);
  const line = (g, done) => {
    const home = g.home === acr;
    const opp = home ? g.away : g.home;
    const right = done
      ? `<span class="res">${home ? g.hs : g.as}:${home ? g.as : g.hs}${g.dec ? " " + esc(g.dec) : ""}</span><span class="wl ${result(g, acr) === "W" ? "w" : "l"}">${result(g, acr)}</span>`
      : `<span class="res nx">${isLive(g) ? `<span class="badge live">${g.hs ?? 0}:${g.as ?? 0}</span>` : esc(timeOf(hass, g.start))}<span class="tv">${esc((g.tv || [])[0] || "")}</span></span><span></span>`;
    return `<div class="gr">
      <span class="small muted" style="white-space:nowrap">${esc(done ? shortDate(hass, g.start) : dayLabel(hass, g.start))}</span>
      <ha-icon icon="${home ? "mdi:home" : "mdi:airplane"}" title="${esc(t(hass, home ? "home" : "away"))}"></ha-icon>
      <span class="clickable" data-club="${esc(opp)}">${logoHtml(data, opp, 22)}</span>
      <span class="clickable" data-club="${esc(opp)}">${esc(teamInfo(data, opp).name)}${rankHtml(data, opp)}</span>
      ${right}
    </div>`;
  };
  return `
    <div class="title">
      <span style="display:flex;align-items:center;gap:10px">${logoHtml(data, acr, 40)}<span>${esc(info.name)}</span></span>
      ${row ? `<span class="badge">#${row.rank} · ${row.pts} ${t(hass, "pts")}</span>` : ""}
    </div>
    <div class="small muted">${formDots(data, acr)}</div>
    <div class="sec">${esc(t(hass, "lastResults"))}</div>
    <div class="rows">${last.length ? last.map((g) => line(g, true)).join("") : `<div class="msg">${esc(t(hass, "none"))}</div>`}</div>
    <div class="sec">${esc(t(hass, "nextGames"))}</div>
    <div class="rows">${next.length ? next.map((g) => line(g, false)).join("") : `<div class="msg">${esc(t(hass, "none"))}</div>`}</div>`;
}

class SwissHockeyClubCard extends SwissHockeyBase {
  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    return clubForm();
  }

  getCardSize() {
    return 7;
  }

  body() {
    return clubHtml(this._hass, this.data, this.team());
  }
}

/* --------------------------------------------------------------- dialog */

let dialogEl = null;

function openClubDialog(hass, acr) {
  if (!dialogEl) {
    dialogEl = document.createElement("swiss-hockey-dialog");
    document.body.appendChild(dialogEl);
  }
  dialogEl.open(hass, acr);
}

class SwissHockeyDialog extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._listener = () => this._render();
    this._key = (ev) => {
      if (ev.key === "Escape") this.close();
    };
  }

  open(hass, acr) {
    this._hass = hass;
    this._acr = acr;
    store.attach(hass, this._listener);
    document.addEventListener("keydown", this._key);
    this._render();
  }

  close() {
    store.detach(this._listener);
    document.removeEventListener("keydown", this._key);
    this._acr = null;
    this.shadowRoot.innerHTML = "";
  }

  _render() {
    if (!this._acr) return;
    this.shadowRoot.innerHTML = `<style>${CSS}
      .back { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 9999; display: flex; align-items: center; justify-content: center; padding: 16px; }
      .box { background: var(--card-background-color, var(--ha-card-background, #fff)); color: var(--primary-text-color); border-radius: var(--ha-card-border-radius, 12px);
             width: min(480px, 100%); max-height: calc(100vh - 32px); overflow: auto; padding: 16px; box-shadow: 0 8px 32px rgba(0,0,0,.35); position: relative;
             font-family: var(--paper-font-body1_-_font-family, inherit); }
      .x { position: absolute; top: 8px; right: 8px; background: none; border: none; font-size: 22px; line-height: 1; cursor: pointer; color: var(--secondary-text-color); padding: 4px 8px; }
      .box .title { padding-right: 32px; }
    </style>
    <div class="back"><div class="box" role="dialog" aria-modal="true">
      <button class="x" aria-label="Close">×</button>
      ${clubHtml(this._hass, store.data, this._acr)}
    </div></div>`;
    const root = this.shadowRoot;
    wireLogos(root);
    root.querySelector(".back").addEventListener("click", (ev) => {
      if (ev.target.classList.contains("back")) this.close();
    });
    root.querySelector(".x").addEventListener("click", () => this.close());
    root.querySelectorAll("[data-club]").forEach((el) =>
      el.addEventListener("click", () => {
        this._acr = el.dataset.club;
        this._render();
      }),
    );
  }
}

/* --------------------------------------------------------- registration */

const define = (name, cls) => {
  if (!customElements.get(name)) customElements.define(name, cls);
};
define("swiss-hockey-next-game", SwissHockeyNextGameCard);
define("swiss-hockey-standings", SwissHockeyStandingsCard);
define("swiss-hockey-club", SwissHockeyClubCard);
define("swiss-hockey-dialog", SwissHockeyDialog);

window.customCards = window.customCards || [];
for (const card of [
  { type: "swiss-hockey-next-game", name: "Swiss Hockey: Next game", description: "Next game of your favourite National League club, with live score." },
  { type: "swiss-hockey-standings", name: "Swiss Hockey: Standings", description: "National League table. Tap a club for details." },
  { type: "swiss-hockey-club", name: "Swiss Hockey: Club", description: "Last results and next games of one club." },
]) {
  if (!window.customCards.some((c) => c.type === card.type)) window.customCards.push({ ...card, preview: true });
}

console.info(`%c SWISS-HOCKEY-CARDS %c ${VERSION} `, "background:#c8102e;color:#fff;font-weight:700", "background:#444;color:#fff");
