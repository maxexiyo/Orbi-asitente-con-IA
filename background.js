importScripts("config.js");
const BASE = `http://127.0.0.1:${ORBI_PORT}`;
const BR = (navigator.userAgent.includes("Edg/") ? "edge" : navigator.userAgent.includes("Brave") ? "brave" : "chrome");
const H = { "Content-Type": "application/json", "X-Orbi-Token": ORBI_TOKEN };

async function post(path, body) {
  try { await fetch(`${BASE}${path}?b=${BR}`, { method: "POST", headers: H, body: JSON.stringify(body) }); } catch (e) {}
}

let pushT = null;
function pushTabs() {
  clearTimeout(pushT);
  pushT = setTimeout(async () => {
    const tabs = await chrome.tabs.query({});
    post("/tabs", { tabs: tabs.map(t => ({ id: t.id, windowId: t.windowId, title: t.title, url: t.url, active: t.active,
      pinned: t.pinned, groupId: t.groupId, audible: t.audible })) });
  }, 400);
}
["onCreated", "onRemoved", "onUpdated", "onActivated", "onMoved", "onAttached", "onDetached"].forEach(e => chrome.tabs[e].addListener(pushTabs));

const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return ""; } };

async function run(op, a) {
  if (op === "cerrar") { await chrome.tabs.remove(a.ids); return { resultado: `Cerré ${a.ids.length} pestaña(s).` }; }
  if (op === "activar") { const t = await chrome.tabs.update(a.id, { active: true }); await chrome.windows.update(t.windowId, { focused: true }); return { resultado: "Listo." }; }
  if (op === "abrir") { await chrome.tabs.create({ url: a.url }); return { resultado: "Abrí la pestaña." }; }
  if (op === "agrupar") {
    const tabs = (await chrome.tabs.query({})).filter(t => !t.pinned && /^https?:/.test(t.url || ""));
    const por = {};
    tabs.forEach(t => (por[`${t.windowId}|${host(t.url)}`] ||= []).push(t));
    const colores = ["blue", "red", "yellow", "green", "pink", "purple", "cyan", "orange", "grey"];
    let n = 0;
    for (const [k, ts] of Object.entries(por)) {
      if (ts.length < (a.minimo || 2)) continue;
      const gid = await chrome.tabs.group({ tabIds: ts.map(t => t.id), createProperties: { windowId: ts[0].windowId } });
      await chrome.tabGroups.update(gid, { title: k.split("|")[1], color: colores[n++ % colores.length] });
    }
    return { resultado: `Agrupé por sitio (${n} grupo/s).` };
  }
  if (op === "desagrupar") {
    const tabs = await chrome.tabs.query({}); const ids = tabs.filter(t => t.groupId > 0).map(t => t.id);
    if (ids.length) await chrome.tabs.ungroup(ids);
    return { resultado: "Quité los grupos." };
  }
  if (op === "ordenar") {
    const wins = await chrome.windows.getAll({ populate: true });
    for (const w of wins) {
      const ts = w.tabs.filter(t => !t.pinned).sort((x, y) => host(x.url).localeCompare(host(y.url)) || (x.title || "").localeCompare(y.title || ""));
      for (let i = 0; i < ts.length; i++) await chrome.tabs.move(ts[i].id, { index: i + w.tabs.filter(t => t.pinned).length });
    }
    return { resultado: "Ordené las pestañas por sitio." };
  }
  return { error: "orden desconocida: " + op };
}

let polling = false;
async function poll() {
  if (polling) return; polling = true;
  while (true) {
    try {
      const r = await fetch(`${BASE}/poll?b=${BR}`, { headers: H });
      const c = await r.json();
      if (c && c.op) {
        let res; try { res = await run(c.op, c.args || {}); } catch (e) { res = { error: String(e) }; }
        await post("/result", { id: c.id, result: res });
        pushTabs();
      }
    } catch (e) { await new Promise(r => setTimeout(r, 3000)); }
  }
}
chrome.alarms.create("orbi", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener(() => { pushTabs(); poll(); });
chrome.runtime.onStartup.addListener(() => { pushTabs(); poll(); });
chrome.runtime.onInstalled.addListener(() => { pushTabs(); poll(); });
pushTabs(); poll();
