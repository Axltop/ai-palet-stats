// Pellet Stats single page app. Plain JavaScript, no build step.
"use strict";

const app = document.getElementById("app");
let OPTIONS = null;

// ---------- helpers ----------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmt(n, digits = 1) {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function currency() {
  try { return localStorage.getItem("currency") || "€"; } catch { return "€"; }
}
const money = (n, digits = 2) => (n === null || n === undefined ? "–" : `${fmt(n, digits)} ${esc(currency())}`);

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 2200);
}

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    out[el.name] = el.value;
  }
  return out;
}

const label = (group, key) => (OPTIONS?.[group]?.[key]) || key || "";
const today = () => new Date().toISOString().slice(0, 10);
const monthName = (ym) => new Date(`${ym}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" });

function seasonSelect(seasons, current, id = "season") {
  const opts = [`<option value="">All time</option>`]
    .concat(seasons.map((s) => `<option value="${esc(s)}" ${s === current ? "selected" : ""}>Season ${esc(s)}</option>`));
  return `<label class="field" style="min-width:12rem">Period<select id="${id}">${opts.join("")}</select></label>`;
}

function tile(labelText, value, unit = "") {
  return `<div class="tile"><div class="label">${esc(labelText)}</div><div class="value">${value} <span class="unit">${esc(unit)}</span></div></div>`;
}

// ---------- charts (inline SVG) ----------

function niceMax(v) {
  if (!v || v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** Vertical bar chart. items: [{label, value, title}] */
function barChart(items, { height = 220, digits = 0, alt = false, everyNth = 0 } = {}) {
  if (!items.length) return `<p class="muted">No data for this period.</p>`;
  const W = 720, H = height, left = 44, bottom = 26, top = 12;
  const max = niceMax(Math.max(...items.map((i) => i.value || 0)));
  const plotW = W - left - 8, plotH = H - top - bottom;
  const slot = plotW / items.length;
  const barW = Math.max(1, Math.min(48, slot * 0.72));
  const step = everyNth || Math.max(1, Math.ceil(items.length / 14));
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">`;
  for (let i = 0; i <= 4; i++) {
    const y = top + plotH - (plotH * i) / 4;
    svg += `<line class="grid-line" x1="${left}" x2="${W - 8}" y1="${y}" y2="${y}"/>`;
    svg += `<text x="${left - 6}" y="${y + 4}" text-anchor="end">${fmt((max * i) / 4, max < 4 ? 1 : 0)}</text>`;
  }
  items.forEach((it, i) => {
    const v = it.value || 0;
    const h = (v / max) * plotH;
    const x = left + i * slot + (slot - barW) / 2;
    const y = top + plotH - h;
    svg += `<rect class="bar${alt ? " alt" : ""}" x="${x}" y="${y}" width="${barW}" height="${Math.max(h, v ? 1 : 0)}" rx="2"><title>${esc(it.title || `${it.label}: ${fmt(v, digits)}`)}</title></rect>`;
    if (items.length <= 14 && v) svg += `<text class="value-label" x="${x + barW / 2}" y="${y - 3}" text-anchor="middle">${fmt(v, digits)}</text>`;
    if (i % step === 0) svg += `<text x="${x + barW / 2}" y="${H - 8}" text-anchor="middle">${esc(it.label)}</text>`;
  });
  return svg + "</svg>";
}

/** Horizontal bar chart for comparing places. */
function hbarChart(items, { digits = 1, unit = "" } = {}) {
  const rows = items.filter((i) => i.value !== null && i.value !== undefined);
  if (!rows.length) return `<p class="muted">Not enough data.</p>`;
  const W = 380, rowH = 30, left = 118, right = 72, H = rows.length * rowH + 8;
  const max = Math.max(...rows.map((r) => r.value)) || 1;
  const minV = Math.min(...rows.map((r) => r.value));
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">`;
  rows.forEach((r, i) => {
    const y = 4 + i * rowH;
    const w = ((W - left - right) * r.value) / max;
    const name = r.label.length > 18 ? r.label.slice(0, 17) + "…" : r.label;
    svg += `<text x="${left - 8}" y="${y + 19}" text-anchor="end">${esc(name)}</text>`;
    svg += `<rect class="bar${r.value === minV && rows.length > 1 ? " alt" : ""}" x="${left}" y="${y + 5}" width="${Math.max(w, 1)}" height="${rowH - 10}" rx="3"><title>${esc(r.label)}: ${fmt(r.value, digits)} ${esc(unit)}</title></rect>`;
    svg += `<text class="value-label" x="${left + w + 6}" y="${y + 19}">${fmt(r.value, digits)} ${esc(unit)}</text>`;
  });
  return svg + "</svg>";
}

/** Daily kg as bars with the mean temperature as a line (own scale on the right). items: [{date, kg, temp_mean}] */
function tempChart(items, { height = 220 } = {}) {
  if (!items.length) return `<p class="muted">No data for this period.</p>`;
  const W = 720, H = height, left = 44, right = 40, bottom = 26, top = 12;
  const plotW = W - left - right, plotH = H - top - bottom;
  const maxKg = niceMax(Math.max(...items.map((i) => i.kg || 0)));
  const temps = items.map((i) => i.temp_mean).filter((t) => t !== null && t !== undefined);
  const tLo = temps.length ? Math.floor(Math.min(0, ...temps) / 5) * 5 : 0;
  const tHi = temps.length ? Math.ceil(Math.max(5, ...temps) / 5) * 5 : 20;
  const ty = (t) => top + plotH - ((t - tLo) / (tHi - tLo || 1)) * plotH;
  const slot = plotW / items.length;
  const barW = Math.max(1, Math.min(24, slot * 0.72));
  const step = Math.max(1, Math.ceil(items.length / 12));
  let svg = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">`;
  for (let i = 0; i <= 4; i++) {
    const y = top + plotH - (plotH * i) / 4;
    svg += `<line class="grid-line" x1="${left}" x2="${W - right}" y1="${y}" y2="${y}"/>`;
    svg += `<text x="${left - 6}" y="${y + 4}" text-anchor="end">${fmt((maxKg * i) / 4, maxKg < 4 ? 1 : 0)}</text>`;
    svg += `<text class="temp-axis" x="${W - right + 6}" y="${y + 4}">${fmt(tLo + ((tHi - tLo) * i) / 4, 0)}°</text>`;
  }
  let path = "";
  items.forEach((it, i) => {
    const x = left + i * slot + (slot - barW) / 2;
    const h = ((it.kg || 0) / maxKg) * plotH;
    const tip = `${it.date}: ${fmt(it.kg, 1)} kg${it.temp_mean != null ? `, mean ${fmt(it.temp_mean, 1)} °C` : ", no temperature"}`;
    svg += `<rect class="bar" x="${x}" y="${top + plotH - h}" width="${barW}" height="${Math.max(h, it.kg ? 1 : 0)}" rx="1"><title>${esc(tip)}</title></rect>`;
    if (it.temp_mean != null) path += `${path && items[i - 1]?.temp_mean != null ? "L" : "M"}${(x + barW / 2).toFixed(1)},${ty(it.temp_mean).toFixed(1)}`;
    if (i % step === 0) svg += `<text x="${x + barW / 2}" y="${H - 8}" text-anchor="middle">${esc(it.date.slice(5))}</text>`;
  });
  if (path) svg += `<path class="temp-line" d="${path}"/>`;
  return svg + "</svg>";
}

// ---------- pages ----------

async function overviewPage(params) {
  const [places, initial] = await Promise.all([api("GET", "/api/places"), api("GET", "/api/compare")]);
  if (!places.length) {
    app.innerHTML = `
      <div class="card empty">
        <h1>Track what your pellet burner eats</h1>
        <p class="muted">Add a place (a house, flat or cottage), add the pellets you buy, then log what you burn.<br>
        You will get consumption per day, month and season, cost, kg per m² and comparisons between places.</p>
        <p class="actions" style="justify-content:center"><a class="btn primary" href="#/places/new">Add your first place</a></p>
        <p class="hint">Just looking around? Restart the app with <code>--demo</code> to load sample data.</p>
      </div>`;
    return;
  }
  const season = params.get("season") ?? initial.available_seasons.at(-1) ?? "";
  const data = season ? await api("GET", `/api/compare?season=${encodeURIComponent(season)}`) : initial;
  const rows = data.places;
  const withData = rows.filter((r) => r.entries);
  const bestId = withData.length > 1
    ? withData.reduce((a, b) => ((b.kg_per_m2_per_day ?? Infinity) < (a.kg_per_m2_per_day ?? Infinity) ? b : a)).place_id
    : null;
  const tot = withData.reduce((acc, r) => ({ kg: acc.kg + r.total_kg, cost: acc.cost + (r.total_cost || 0) }), { kg: 0, cost: 0 });

  app.innerHTML = `
    <div class="page-head">
      <div><h1>Overview</h1><div class="muted">${rows.length} place${rows.length === 1 ? "" : "s"} · ${season ? `heating season ${esc(season)} (1 Jul – 30 Jun)` : "all time"}</div></div>
      ${seasonSelect(data.available_seasons, season)}
    </div>
    <div class="grid-tight" style="margin-bottom:1rem">
      ${tile("Pellets burned", fmt(tot.kg, 0), "kg")}
      ${tile("Bags (15 kg equivalent)", fmt(tot.kg / 15, 0), "")}
      ${tile("Total cost", money(tot.cost, 0))}
      ${tile("Average price", tot.kg ? money(tot.cost / tot.kg, 3) : "–", "/ kg")}
    </div>
    <div class="card">
      <h2>Compare places</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Place</th><th>Heating</th><th class="num">Area</th><th class="num">Days</th><th class="num">kg</th><th class="num">kg / day</th>
          <th class="num">kg / m²</th><th class="num">g / m² / day</th><th class="num">Cost</th><th class="num">Cost / m²</th><th class="num">Price / kg</th></tr></thead>
        <tbody>${rows.map((r) => `
          <tr class="${r.place_id === bestId ? "best" : ""}">
            <td><a href="#/places/${r.place_id}${season ? `?season=${encodeURIComponent(season)}` : ""}">${esc(r.name)}</a></td>
            <td>${esc(label("heating_types", r.heating_type))}</td>
            <td class="num">${fmt(r.area_m2, 0)} m²</td>
            <td class="num">${r.days || "–"}</td>
            <td class="num">${fmt(r.total_kg, 0)}</td>
            <td class="num">${fmt(r.kg_per_day)}</td>
            <td class="num">${fmt(r.kg_per_m2)}</td>
            <td class="num">${r.kg_per_m2_per_day === null ? "–" : fmt(r.kg_per_m2_per_day * 1000, 0)}</td>
            <td class="num">${money(r.total_cost, 0)}</td>
            <td class="num">${money(r.cost_per_m2)}</td>
            <td class="num">${money(r.price_per_kg, 3)}</td>
          </tr>`).join("")}</tbody>
      </table></div>
      <p class="hint">“g / m² / day” divides by both area and the number of days logged, so places logged over different periods compare fairly.
      ${bestId ? "The highlighted row is the most efficient place." : ""}</p>
    </div>
    <div class="grid">
      <div class="card"><h3>kg per m²</h3>${hbarChart(rows.map((r) => ({ label: r.name, value: r.kg_per_m2 })), { unit: "kg" })}</div>
      <div class="card"><h3>g per m² per day</h3>${hbarChart(rows.map((r) => ({ label: r.name, value: r.kg_per_m2_per_day === null ? null : r.kg_per_m2_per_day * 1000 })), { digits: 0, unit: "g" })}</div>
      <div class="card"><h3>kg per day</h3>${hbarChart(rows.map((r) => ({ label: r.name, value: r.kg_per_day })), { unit: "kg" })}</div>
      <div class="card"><h3>Cost per m²</h3>${hbarChart(rows.map((r) => ({ label: r.name, value: r.cost_per_m2 })), { digits: 2, unit: currency() })}</div>
    </div>`;
  document.getElementById("season").onchange = (e) => go(`#/?season=${encodeURIComponent(e.target.value)}`);
}

function placeTags(p) {
  const t = [
    label("heating_types", p.heating_type),
    `${fmt(p.area_m2, 0)} m²`,
    p.ceiling_height_m && `${fmt(p.ceiling_height_m, 2)} m ceilings`,
    p.insulation_type && `Insulation: ${label("insulation_types", p.insulation_type)}`,
    p.window_type && label("window_types", p.window_type),
    p.building_year && `Built ${p.building_year}`,
    p.climate_zone && `${label("climate_zones", p.climate_zone)} climate`,
    p.target_temp_c != null && `Target ${fmt(p.target_temp_c, 1)} °C`,
    p.burner_power_kw && `${fmt(p.burner_power_kw, 0)} kW burner`,
    p.occupants && `${p.occupants} occupant${p.occupants === 1 ? "" : "s"}`,
  ].filter(Boolean);
  return `<div class="tags">${t.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>`;
}

async function placesPage() {
  const places = await api("GET", "/api/places");
  app.innerHTML = `
    <div class="page-head"><div><h1>Places</h1><div class="muted">Each place has its own statistics.</div></div>
      <a class="btn primary" href="#/places/new">+ Add place</a></div>
    ${places.length ? `<div class="grid">${places.map((p) => `
      <a class="card place-card" href="#/places/${p.id}">
        <h2>${esc(p.name)}</h2>
        ${placeTags(p)}
        <div class="muted small">${p.entry_count} entries · ${fmt(p.total_kg, 0)} kg logged${p.last_entry ? ` · last ${esc(p.last_entry)}` : ""}</div>
      </a>`).join("")}</div>`
      : `<div class="card empty"><p class="muted">No places yet.</p><a class="btn primary" href="#/places/new">Add your first place</a></div>`}`;
}

function selectField(name, text, group, value, required = false) {
  const opts = Object.entries(OPTIONS[group]).map(([k, v]) => `<option value="${esc(k)}" ${k === value ? "selected" : ""}>${esc(v)}</option>`);
  return `<label class="field"><span class="${required ? "req" : ""}">${text}</span>
    <select name="${name}" ${required ? "required" : ""}>${required ? "" : `<option value="">–</option>`}${opts.join("")}</select></label>`;
}

function inputField(name, text, value, attrs = "", required = false) {
  return `<label class="field"><span class="${required ? "req" : ""}">${text}</span>
    <input name="${name}" value="${esc(value ?? "")}" ${attrs} ${required ? "required" : ""}></label>`;
}

async function placeFormPage(id) {
  const p = id ? await api("GET", `/api/places/${id}`) : {};
  app.innerHTML = `
    <div class="page-head"><h1>${id ? `Edit ${esc(p.name)}` : "Add a place"}</h1></div>
    <form class="card stack" id="place-form">
      ${inputField("name", "Name", p.name, 'placeholder="e.g. Family house"', true)}
      ${selectField("heating_type", "Heating type", "heating_types", p.heating_type, true)}
      ${inputField("area_m2", "Heated area (m²)", p.area_m2, 'type="number" step="0.1" min="1"', true)}
      ${inputField("ceiling_height_m", "Ceiling height (m)", p.ceiling_height_m, 'type="number" step="0.01" min="0" placeholder="2.6"')}
      ${selectField("window_type", "Windows", "window_types", p.window_type)}
      ${selectField("insulation_type", "Insulation", "insulation_types", p.insulation_type)}
      ${inputField("building_year", "Year built", p.building_year, 'type="number" min="1800" max="2100"')}
      ${selectField("climate_zone", "Climate zone", "climate_zones", p.climate_zone)}
      ${inputField("target_temp_c", "Target temperature (°C)", p.target_temp_c, 'type="number" step="0.5" min="0" max="35"')}
      ${inputField("burner_power_kw", "Burner power (kW)", p.burner_power_kw, 'type="number" step="0.1" min="0"')}
      ${inputField("occupants", "Occupants", p.occupants, 'type="number" min="0" step="1"')}
      <fieldset class="full coords">
        <legend>Location, for outdoor temperatures from OpenWeather</legend>
        ${OPTIONS.weather_enabled ? `<div class="actions"><input id="town" placeholder="Town or village, e.g. Sofia, BG" style="flex:1;min-width:12rem">
          <button type="button" id="find-town">Find coordinates</button></div><div id="town-results" class="actions"></div>` : ""}
        <div class="actions">
          ${inputField("latitude", "Latitude", p.latitude, 'type="number" step="any" min="-90" max="90" placeholder="42.6977"')}
          ${inputField("longitude", "Longitude", p.longitude, 'type="number" step="any" min="-180" max="180" placeholder="23.3219"')}
        </div>
        ${OPTIONS.weather_enabled ? "" : `<p class="hint">Temperatures are off because no OpenWeather API key is set. See the README. You can still enter coordinates now.</p>`}
      </fieldset>
      <label class="field full">Notes<textarea name="notes">${esc(p.notes || "")}</textarea></label>
      <div class="actions full">
        <button class="primary" type="submit">${id ? "Save changes" : "Add place"}</button>
        <a class="btn" href="${id ? `#/places/${id}` : "#/places"}">Cancel</a>
        <span class="error" id="form-error"></span>
      </div>
    </form>`;
  const findTown = document.getElementById("find-town");
  if (findTown) {
    const town = document.getElementById("town");
    const results = document.getElementById("town-results");
    const lookup = async () => {
      results.innerHTML = `<span class="hint">Looking up…</span>`;
      try {
        const found = await api("GET", `/api/geocode?q=${encodeURIComponent(town.value)}`);
        results.innerHTML = found.length
          ? found.map((r, i) => `<button type="button" class="link" data-i="${i}">${esc([r.name, r.state, r.country].filter(Boolean).join(", "))} (${r.lat}, ${r.lon})</button>`).join("")
          : `<span class="hint">Nothing found. Try adding the country code, e.g. “Bansko, BG”.</span>`;
        results.querySelectorAll("button").forEach((b) => {
          b.onclick = () => {
            const r = found[b.dataset.i];
            const form = document.getElementById("place-form");
            form.latitude.value = r.lat; form.longitude.value = r.lon;
            results.innerHTML = `<span class="hint">Using ${esc(r.name)}.</span>`;
          };
        });
      } catch (err) {
        results.innerHTML = `<span class="error">${esc(err.message)}</span>`;
      }
    };
    findTown.onclick = lookup;
    town.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); lookup(); } };
  }
  document.getElementById("place-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const saved = await api(id ? "PUT" : "POST", id ? `/api/places/${id}` : "/api/places", formData(e.target));
      toast(id ? "Place saved" : "Place added");
      go(`#/places/${saved.id}`);
    } catch (err) {
      document.getElementById("form-error").textContent = err.message;
    }
  };
}

async function placeDetailPage(id, params) {
  const [place, all, stock] = await Promise.all([
    api("GET", `/api/places/${id}`), api("GET", `/api/places/${id}/stats`), api("GET", `/api/places/${id}/stock`)]);
  const season = params.get("season") ?? all.available_seasons.at(-1) ?? "";
  const st = season ? await api("GET", `/api/places/${id}/stats?season=${encodeURIComponent(season)}`) : all;
  const metric = params.get("metric") || "kg";
  const s = st.summary;
  const entries = (await api("GET", `/api/entries?place_id=${id}`))
    .filter((e) => !season || seasonOf(e.date) === season);

  const monthlyItems = st.monthly.map((m) => ({
    label: monthName(m.month),
    value: metric === "cost" ? m.cost : metric === "per_day" ? m.kg_per_day : m.kg,
    title: `${monthName(m.month)}: ${fmt(m.kg, 0)} kg, ${fmt(m.kg_per_day)} kg/day, ${fmt(m.cost, 2)} ${currency()}`,
  }));
  const dailyItems = st.daily.slice(-120).map((d) => ({
    label: d.date.slice(5),
    value: d.kg,
    title: `${d.date}: ${fmt(d.kg, 1)} kg`,
  }));
  const metricBtn = (key, text) => `<button type="button" data-metric="${key}" class="${metric === key ? "on" : ""}">${text}</button>`;

  app.innerHTML = `
    <div class="page-head">
      <div><h1>${esc(place.name)}</h1>${placeTags(place)}</div>
      <div class="actions">
        ${seasonSelect(all.available_seasons, season)}
        <a class="btn primary" href="#/log?place=${id}">+ Log consumption</a>
        <a class="btn" href="#/storage?place=${id}">+ Bags to storage</a>
        <a class="btn" href="#/places/${id}/edit">Edit</a>
        <button class="danger" id="delete-place">Delete</button>
      </div>
    </div>
    ${stockLine(stock, id)}
    ${s.entries ? `
    <div class="grid-tight" style="margin-bottom:1rem">
      ${tile("Burned", fmt(s.total_kg, 0), "kg")}
      ${tile("Per day", fmt(s.kg_per_day), "kg")}
      ${tile("Per m²", fmt(s.kg_per_m2), "kg")}
      ${tile("Per m³", fmt(s.kg_per_m3), "kg")}
      ${tile("Per m² per day", s.kg_per_m2_per_day === null ? "–" : fmt(s.kg_per_m2_per_day * 1000, 0), "g")}
      ${tile("Cost", money(s.total_cost, 0))}
      ${tile("Cost per day", money(s.cost_per_day))}
      ${tile("Cost per m²", money(s.cost_per_m2))}
      ${tile("Average price", money(s.price_per_kg, 3), "/ kg")}
      ${tile("Period", s.days, `days · ${s.entries} entries`)}
    </div>
    <div class="card">
      <div class="page-head" style="margin-bottom:.5rem"><h2 style="margin:0">Per month</h2>
        <div class="segmented" id="metric">${metricBtn("kg", "kg")}${metricBtn("per_day", "kg / day")}${metricBtn("cost", "Cost")}</div></div>
      ${barChart(monthlyItems, { digits: metric === "per_day" ? 1 : 0 })}
      <p class="hint">kg / day divides each month by the days inside the logged period, so a partly logged first or last month is not understated.</p>
    </div>
    <div class="card"><h2>Per day ${st.daily.length > 120 ? `<span class="muted small">(last 120 days of the period)</span>` : ""}</h2>
      ${barChart(dailyItems, { height: 180, digits: 1, alt: true })}
      <p class="hint">Each bar is what you logged that day. If you log refills every few days, look at the monthly kg / day instead.</p></div>
    <div class="card" id="weather"></div>
    ${st.monthly.some((m) => m.temp_mean != null) ? `<div class="card"><h2>Consumption and temperature per month</h2><div class="table-wrap"><table>
      <thead><tr><th>Month</th><th class="num">kg</th><th class="num">kg / day</th><th class="num">Mean temp</th><th class="num">Degree days</th><th class="num">kg / degree day</th></tr></thead>
      <tbody>${st.monthly.map((m) => `<tr><td>${esc(monthName(m.month))}</td><td class="num">${fmt(m.kg, 0)}</td><td class="num">${fmt(m.kg_per_day)}</td>
        <td class="num">${m.temp_mean == null ? "–" : `${fmt(m.temp_mean, 1)} °C`}${m.temp_mean != null && m.days_with_temp < m.days ? ` <span class="muted small">(${m.days_with_temp}/${m.days} d)</span>` : ""}</td>
        <td class="num">${fmt(m.hdd, 0)}</td><td class="num">${fmt(m.kg_per_hdd, 2)}</td></tr>`).join("")}</tbody></table></div>
      <p class="hint">kg / degree day is shown for months where every logged day has a temperature. It stays about the same in mild and cold months if the house behaves the same, so it is a fair way to compare winters.</p></div>` : ""}
    <div class="grid">
      <div class="card"><h2>Per season</h2><div class="table-wrap"><table>
        <thead><tr><th>Season</th><th class="num">kg</th><th class="num">kg / day</th><th class="num">kg / m²</th><th class="num">Cost</th><th class="num">Cost / m²</th></tr></thead>
        <tbody>${all.seasons.map((x) => `<tr><td><a href="#/places/${id}?season=${encodeURIComponent(x.season)}">${esc(x.season)}</a> <span class="muted small">${x.days} d</span></td>
          <td class="num">${fmt(x.kg, 0)}</td><td class="num">${fmt(x.kg_per_day)}</td><td class="num">${fmt(x.kg_per_m2)}</td>
          <td class="num">${money(x.cost, 0)}</td><td class="num">${money(x.cost_per_m2)}</td></tr>`).join("")}</tbody></table></div>
        <p class="hint">Seasons run 1 July to 30 June. This table always shows every season.</p></div>
      <div class="card"><h2>By pellet</h2><div class="table-wrap"><table>
        <thead><tr><th>Pellet</th><th class="num">kg</th><th class="num">Share</th><th class="num">Cost</th><th class="num">Price / kg</th></tr></thead>
        <tbody>${st.brands.map((b) => `<tr><td>${esc(b.brand)}</td><td class="num">${fmt(b.kg, 0)}</td><td class="num">${fmt(b.share)} %</td>
          <td class="num">${money(b.cost, 0)}</td><td class="num">${money(b.price_per_kg, 3)}</td></tr>`).join("")}</tbody></table></div></div>
    </div>` : `<div class="card empty"><p class="muted">Nothing logged ${season ? "in this season" : "yet"}.</p><a class="btn primary" href="#/log?place=${id}">Log consumption</a></div>`}
    ${entriesTable(entries, false)}`;

  const yesterday = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  let from = params.get("from"), to = params.get("to");
  if (!from || !to) {
    if (season) {
      const start = Number(season.split("/")[0]);
      from = `${start}-07-01`; to = `${start + 1}-06-30`;
      if (s.first_date && s.first_date > from) from = s.first_date;
      if (to > yesterday) to = yesterday;
    } else {
      from = s.first_date || yesterday.slice(0, 8) + "01"; to = s.last_date && s.last_date < yesterday ? s.last_date : yesterday;
    }
    if (from > to) from = to;
  }
  weatherCard(place, from, to, season, metric);
  document.getElementById("season").onchange = (e) => go(`#/places/${id}?season=${encodeURIComponent(e.target.value)}&metric=${metric}`);
  document.querySelectorAll("#metric button").forEach((b) => {
    b.onclick = () => go(`#/places/${id}?season=${encodeURIComponent(season)}&metric=${b.dataset.metric}`);
  });
  document.getElementById("delete-place").onclick = async () => {
    if (!confirm(`Delete "${place.name}" and all ${all.summary.entries} of its entries? This cannot be undone.`)) return;
    await api("DELETE", `/api/places/${id}`);
    toast("Place deleted");
    go("#/places");
  };
  bindEntryButtons();
}

function stockLine(stock, placeId) {
  if (!stock.since) {
    return `<p class="hint">Record the bags you buy under <a href="#/storage?place=${placeId}">Storage</a> to see how much is left.</p>`;
  }
  const bags = stock.products.filter((p) => p.bags !== null && p.kg !== 0)
    .map((p) => `${fmt(p.bags, p.bags % 1 ? 1 : 0)} × ${esc(p.brand)}`).join(", ");
  return `<div class="card stock ${stock.kg < 0 ? "low" : ""}"><strong>In storage: ${fmt(stock.kg, 0)} kg</strong>${bags ? ` <span class="muted">(${bags} bags)</span>` : ""}
    <span class="muted small">· ${fmt(stock.delivered_kg, 0)} kg put in, ${fmt(stock.burned_kg, 0)} kg burned since ${esc(stock.since)}</span>
    <a class="btn link" href="#/storage?place=${placeId}">Storage</a></div>`;
}

async function weatherCard(place, from, to, season, metric) {
  const el = document.getElementById("weather");
  const base = `#/places/${place.id}?season=${encodeURIComponent(season)}&metric=${metric}`;
  const render = (w, busy = "") => {
    const ready = w.enabled && w.has_location;
    el.innerHTML = `
      <div class="page-head" style="margin-bottom:.5rem"><h2 style="margin:0">Outdoor temperature</h2>
        <form class="actions" id="weather-period">
          <label class="field">From<input type="date" name="from" value="${esc(from)}" required></label>
          <label class="field">To<input type="date" name="to" value="${esc(to)}" required></label>
          <button type="submit">Show</button>
        </form></div>
      ${!w.enabled ? `<p class="hint">Add an OpenWeather API key to get daily temperatures. See “Outdoor temperatures” in the README.</p>`
        : !w.has_location ? `<p class="hint"><a href="#/places/${place.id}/edit">Add this place's location</a> to get its daily temperatures.</p>` : ""}
      ${ready && w.missing ? `<p class="actions"><button class="primary" id="fetch-weather" ${busy ? "disabled" : ""}>Get ${w.missing} missing day${w.missing === 1 ? "" : "s"} from OpenWeather</button>
        <span class="hint">${esc(busy) || "Each day is one API call and is saved, so it is only fetched once."}</span></p>` : ""}
      ${w.days_with_temp ? `
      <div class="grid-tight" style="margin-bottom:1rem">
        ${tile("Mean daily temperature", fmt(w.temp_mean, 1), "°C")}
        ${tile("Coldest / warmest", `${fmt(w.temp_min, 0)} / ${fmt(w.temp_max, 0)}`, "°C")}
        ${tile("Heating degree days", fmt(w.hdd, 0), "")}
        ${tile("Burned", fmt(w.kg, 0), "kg")}
        ${tile("Per day", fmt(w.kg_per_day), "kg")}
        ${tile("Per degree day", fmt(w.kg_per_hdd, 2), "kg")}
      </div>
      ${tempChart(w.daily.slice(-180))}
      <p class="legend"><span><i style="background:var(--bar)"></i>kg burned per day</span><span><i style="background:var(--temp)"></i>mean temperature (right scale)</span></p>
      <p class="hint">${w.days_with_temp} of ${w.days} days have a temperature${w.daily.length > 180 ? "; the chart shows the last 180 days" : ""}.
        Degree days: ${fmt(w.hdd_base, 0)} °C minus the day's mean, for days at ${fmt(w.hdd_threshold, 0)} °C or colder.${w.kg_per_hdd == null ? " kg per degree day appears once every day in the period has a temperature." : ""}</p>`
        : ready && !w.missing ? `<p class="muted">No past days in this period.</p>` : ""}`;
    document.getElementById("weather-period").onsubmit = (e) => {
      e.preventDefault();
      const d = formData(e.target);
      go(`${base}&from=${d.from}&to=${d.to}`);
    };
    const btn = document.getElementById("fetch-weather");
    if (btn) btn.onclick = () => fetchAll(w.missing);
  };
  const q = `from=${from}&to=${to}`;
  const fetchAll = async (total) => {
    let w, done = 0;
    try {
      do {
        render(w || current, `Fetching… ${done} of ${total}`);
        w = await api("POST", `/api/places/${place.id}/weather/fetch?${q}`);
        done += w.fetched;
      } while (w.missing && w.fetched);
      toast(`Got ${done} day${done === 1 ? "" : "s"} of temperatures`);
      route();  // reload so the monthly table picks up the new temperatures
    } catch (err) {
      render(w || current);
      el.insertAdjacentHTML("beforeend", `<p class="error">${esc(err.message)}</p>`);
    }
  };
  let current;
  try {
    current = await api("GET", `/api/places/${place.id}/weather?${q}`);
    render(current);
  } catch (err) {
    el.innerHTML = `<h2>Outdoor temperature</h2><p class="error">${esc(err.message)}</p>`;
  }
}

// The stored cost of an entry, if it differs from what the pellet price would give (a manual override).
function costOverride(entry, pellets) {
  if (!entry.id || entry.cost === null) return "";
  const p = pellets.find((x) => x.id === entry.pellet_id);
  if (!p || p.price_per_bag == null) return entry.cost;
  const auto = Math.round((entry.kg * p.price_per_bag / p.bag_weight_kg) * 100) / 100;
  return Math.abs(auto - entry.cost) < 0.005 ? "" : entry.cost;
}

function seasonOf(iso) {
  const [y, m] = iso.split("-").map(Number);
  const start = m >= 7 ? y : y - 1;
  return `${start}/${String(start + 1).slice(-2)}`;
}

function entriesTable(entries, showPlace) {
  if (!entries.length) return "";
  const shown = entries.slice(0, 200);
  return `<div class="card"><div class="page-head" style="margin-bottom:.5rem"><h2 style="margin:0">Log entries</h2>
      <a class="btn" href="/api/export.csv${showPlace ? "" : `?place_id=${entries[0].place_id}`}">Export CSV</a></div>
    <div class="table-wrap"><table>
    <thead><tr><th>Date</th>${showPlace ? "<th>Place</th>" : ""}<th>Pellet</th><th class="num">Bags</th><th class="num">kg</th><th class="num">Cost</th><th>Notes</th><th></th></tr></thead>
    <tbody>${shown.map((e) => `<tr>
      <td>${esc(e.date)}</td>${showPlace ? `<td>${esc(e.place_name)}</td>` : ""}<td>${esc(e.brand || "–")}</td>
      <td class="num">${e.bags === null ? "–" : fmt(e.bags, e.bags % 1 ? 1 : 0)}</td><td class="num">${fmt(e.kg, 1)}</td>
      <td class="num">${money(e.cost)}</td><td class="small muted">${esc(e.notes || "")}</td>
      <td><a class="btn link" href="#/log/${e.id}">Edit</a><button class="link danger" data-delete-entry="${e.id}">Delete</button></td>
    </tr>`).join("")}</tbody></table></div>
    ${entries.length > shown.length ? `<p class="hint">Showing the latest ${shown.length} of ${entries.length} entries. Export CSV for all of them.</p>` : ""}</div>`;
}

function bindEntryButtons() {
  document.querySelectorAll("[data-delete-entry]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Delete this entry?")) return;
      await api("DELETE", `/api/entries/${b.dataset.deleteEntry}`);
      toast("Entry deleted");
      route();
    };
  });
}

async function logPage(entryId, params) {
  const [places, pellets] = await Promise.all([api("GET", "/api/places"), api("GET", "/api/pellets")]);
  if (!places.length) {
    app.innerHTML = `<div class="card empty"><p>Add a place first, then you can log what it burns.</p><a class="btn primary" href="#/places/new">Add place</a></div>`;
    return;
  }
  let entry = {};
  if (entryId) {
    entry = await api("GET", `/api/entries/${entryId}`);
  }
  let lastPellet = "";
  try { lastPellet = localStorage.getItem("lastPellet") || ""; } catch { /* storage unavailable */ }
  const placeId = String(entry.place_id || params.get("place") || places[0].id);
  const pelletId = String(entry.pellet_id ?? (entryId ? "" : (pellets.some((p) => String(p.id) === lastPellet) ? lastPellet : pellets[0]?.id ?? "")));
  let mode = entry.id ? (entry.bags !== null && entry.pellet_id ? "bags" : "kg") : (pellets.length ? "bags" : "kg");

  app.innerHTML = `
    <div class="page-head"><div><h1>${entryId ? "Edit entry" : "Log consumption"}</h1>
      <div class="muted">Log the pellets you put into the burner. Logging every refill (every day or every few days) works best.</div></div></div>
    <form class="card stack" id="entry-form">
      <label class="field"><span class="req">Place</span><select name="place_id" required>
        ${places.map((p) => `<option value="${p.id}" ${String(p.id) === placeId ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
      ${inputField("date", "Date", entry.date || today(), 'type="date"', true)}
      <label class="field">Pellet<select name="pellet_id">
        <option value="">– not specified –</option>
        ${pellets.map((p) => `<option value="${p.id}" ${String(p.id) === pelletId ? "selected" : ""}>${esc(p.brand)}${p.name ? " " + esc(p.name) : ""} · ${fmt(p.bag_weight_kg, 0)} kg bag${p.price_per_bag != null ? ` · ${money(p.price_per_bag)}` : ""}</option>`).join("")}
      </select>${pellets.length ? "" : `<span class="hint"><a href="#/pellets">Add your pellets</a> to log by bags and get costs.</span>`}</label>
      <label class="field">Amount
        <span class="actions"><span class="segmented" id="mode"><button type="button" data-mode="bags">Bags</button><button type="button" data-mode="kg">kg</button></span>
        <input name="amount" type="number" step="any" min="0" required style="flex:1;min-width:6rem" value="${esc(entry.id ? (mode === "bags" ? entry.bags : entry.kg) : "")}"></span></label>
      ${inputField("cost", "Cost override", costOverride(entry, pellets), `type="number" step="0.01" min="0" placeholder="from pellet price"`)}
      <label class="field full">Notes<input name="notes" value="${esc(entry.notes || "")}" placeholder="e.g. very cold week, cleaned burner"></label>
      <div class="full hint" id="preview"></div>
      <div class="actions full">
        <button class="primary" type="submit">${entryId ? "Save entry" : "Log it"}</button>
        ${entryId ? `<a class="btn" href="#/places/${entry.place_id}">Cancel</a>` : `<label class="small"><input type="checkbox" id="another"> log another after this</label>`}
        <span class="error" id="form-error"></span>
      </div>
    </form>
    <div id="recent"></div>`;

  const form = document.getElementById("entry-form");
  const pelletById = (pid) => pellets.find((p) => String(p.id) === String(pid));
  const refresh = () => {
    document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    const p = pelletById(form.pellet_id.value);
    const amt = parseFloat(form.amount.value);
    let text = "";
    if (mode === "bags" && !p) text = "Pick a pellet product to log by bags, or switch to kg.";
    else if (amt > 0) {
      const kg = mode === "bags" ? amt * p.bag_weight_kg : amt;
      const cost = form.cost.value !== "" ? parseFloat(form.cost.value) : p && p.price_per_bag != null ? (kg * p.price_per_bag) / p.bag_weight_kg : null;
      text = `= ${fmt(kg, 1)} kg${cost != null ? ` · ${money(cost)}` : " · no price, cost not tracked"}`;
    }
    document.getElementById("preview").textContent = text;
  };
  document.querySelectorAll("#mode button").forEach((b) => { b.onclick = () => { mode = b.dataset.mode; refresh(); }; });
  form.oninput = refresh;
  refresh();

  const showRecent = async () => {
    const recent = (await api("GET", `/api/entries?place_id=${form.place_id.value}`)).slice(0, 5);
    document.getElementById("recent").innerHTML = entryId ? "" : entriesTable(recent, false).replace("Log entries", "Latest entries for this place");
    bindEntryButtons();
  };
  form.place_id.addEventListener("change", showRecent);
  showRecent();

  form.onsubmit = async (e) => {
    e.preventDefault();
    const d = formData(form);
    const body = { place_id: d.place_id, date: d.date, pellet_id: d.pellet_id || null, notes: d.notes, cost: d.cost };
    body[mode] = d.amount;
    try {
      const saved = await api(entryId ? "PUT" : "POST", entryId ? `/api/entries/${entryId}` : "/api/entries", body);
      try { localStorage.setItem("lastPellet", d.pellet_id); } catch { /* ignore */ }
      toast(`Logged ${fmt(saved.kg, 1)} kg`);
      if (!entryId && document.getElementById("another").checked) {
        form.amount.value = ""; form.notes.value = ""; form.cost.value = "";
        refresh(); showRecent(); form.amount.focus();
      } else {
        go(`#/places/${saved.place_id}`);
      }
    } catch (err) {
      document.getElementById("form-error").textContent = err.message;
    }
  };
}

async function storagePage(params) {
  const [places, pellets, stocks, deliveries] = await Promise.all([
    api("GET", "/api/places"), api("GET", "/api/pellets"), api("GET", "/api/stock"), api("GET", "/api/deliveries")]);
  if (!places.length) {
    app.innerHTML = `<div class="card empty"><p>Add a place first, then you can record the bags you put into its storage.</p><a class="btn primary" href="#/places/new">Add place</a></div>`;
    return;
  }
  const editId = params.get("edit");
  const d = editId ? await api("GET", `/api/deliveries/${editId}`) : {};
  const placeId = String(d.place_id || params.get("place") || places[0].id);
  let lastPellet = "";
  try { lastPellet = localStorage.getItem("lastPellet") || ""; } catch { /* storage unavailable */ }
  const pelletId = String(d.pellet_id ?? (editId ? "" : (pellets.some((p) => String(p.id) === lastPellet) ? lastPellet : pellets[0]?.id ?? "")));
  let mode = d.id ? (d.bags !== null && d.pellet_id ? "bags" : "kg") : (pellets.length ? "bags" : "kg");

  app.innerHTML = `
    <div class="page-head"><div><h1>Storage</h1>
      <div class="muted">Record the bags you buy or put into storage. What is left is those bags minus what you log as burned from that date on.</div></div></div>
    <div class="grid-tight" style="margin-bottom:1rem">
      ${stocks.map((x) => `<a class="tile place-card ${x.kg < 0 ? "low" : ""}" href="#/storage?place=${x.place_id}">
        <div class="label">${esc(x.name)}</div>
        <div class="value">${x.since ? fmt(x.kg, 0) : "–"} <span class="unit">kg left</span></div>
        <div class="small muted">${x.since ? x.products.filter((p) => p.bags !== null && p.kg !== 0).map((p) => `${fmt(p.bags, p.bags % 1 ? 1 : 0)} bags ${esc(p.brand)}`).join("<br>") || "&nbsp;" : "no bags recorded yet"}</div>
      </a>`).join("")}
    </div>
    <form class="card stack" id="delivery-form">
      <h2 class="full" style="margin:0">${d.id ? "Edit delivery" : "Add bags to storage"}</h2>
      <label class="field"><span class="req">Place</span><select name="place_id" required>
        ${places.map((p) => `<option value="${p.id}" ${String(p.id) === placeId ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
      ${inputField("date", "Date", d.date || today(), 'type="date"', true)}
      <label class="field">Pellet<select name="pellet_id">
        <option value="">– not specified –</option>
        ${pellets.map((p) => `<option value="${p.id}" ${String(p.id) === pelletId ? "selected" : ""}>${esc(p.brand)}${p.name ? " " + esc(p.name) : ""} · ${fmt(p.bag_weight_kg, 0)} kg bag${p.price_per_bag != null ? ` · ${money(p.price_per_bag)}` : ""}</option>`).join("")}
      </select>${pellets.length ? "" : `<span class="hint"><a href="#/pellets">Add your pellets</a> to enter bags and get costs.</span>`}</label>
      <label class="field">Amount
        <span class="actions"><span class="segmented" id="mode"><button type="button" data-mode="bags">Bags</button><button type="button" data-mode="kg">kg</button></span>
        <input name="amount" type="number" step="any" min="0" required style="flex:1;min-width:6rem" value="${esc(d.id ? (mode === "bags" ? d.bags : d.kg) : "")}"></span></label>
      ${inputField("cost", "Total paid", costOverride(d, pellets), `type="number" step="0.01" min="0" placeholder="from pellet price"`)}
      <label class="field full">Notes<input name="notes" value="${esc(d.notes || "")}" placeholder="e.g. shop, delivery, pallet of 65 bags"></label>
      <div class="full hint" id="preview"></div>
      <div class="actions full">
        <button class="primary" type="submit">${d.id ? "Save" : "Add to storage"}</button>
        ${d.id ? `<a class="btn" href="#/storage?place=${d.place_id}">Cancel</a>` : ""}
        <span class="error" id="form-error"></span>
      </div>
    </form>
    <div id="deliveries"></div>`;

  const form = document.getElementById("delivery-form");
  const pelletById = (pid) => pellets.find((p) => String(p.id) === String(pid));
  const refresh = () => {
    document.querySelectorAll("#mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === mode));
    const p = pelletById(form.pellet_id.value);
    const amt = parseFloat(form.amount.value);
    let text = "";
    if (mode === "bags" && !p) text = "Pick a pellet product to enter bags, or switch to kg.";
    else if (amt > 0) {
      const kg = mode === "bags" ? amt * p.bag_weight_kg : amt;
      const cost = form.cost.value !== "" ? parseFloat(form.cost.value) : p && p.price_per_bag != null ? (kg * p.price_per_bag) / p.bag_weight_kg : null;
      text = `= ${fmt(kg, 1)} kg${cost != null ? ` · ${money(cost)}` : ""}`;
    }
    document.getElementById("preview").textContent = text;
  };
  document.querySelectorAll("#mode button").forEach((b) => { b.onclick = () => { mode = b.dataset.mode; refresh(); }; });
  form.oninput = refresh;
  refresh();

  const showList = () => {
    const rows = deliveries.filter((x) => String(x.place_id) === form.place_id.value);
    const name = places.find((p) => String(p.id) === form.place_id.value)?.name || "";
    document.getElementById("deliveries").innerHTML = `<div class="card"><h2>Bags put into storage · ${esc(name)}</h2>
      ${rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Date</th><th>Pellet</th><th class="num">Bags</th><th class="num">kg</th><th class="num">Paid</th><th>Notes</th><th></th></tr></thead>
      <tbody>${rows.map((x) => `<tr><td>${esc(x.date)}</td><td>${esc(x.brand || "–")}</td>
        <td class="num">${x.bags === null ? "–" : fmt(x.bags, x.bags % 1 ? 1 : 0)}</td><td class="num">${fmt(x.kg, 1)}</td>
        <td class="num">${money(x.cost)}</td><td class="small muted">${esc(x.notes || "")}</td>
        <td><a class="btn link" href="#/storage?edit=${x.id}">Edit</a><button class="link danger" data-delete-delivery="${x.id}">Delete</button></td></tr>`).join("")}</tbody>
      </table></div>` : `<p class="muted">Nothing recorded for this place yet.</p>`}</div>`;
    document.querySelectorAll("[data-delete-delivery]").forEach((b) => {
      b.onclick = async () => {
        if (!confirm("Delete this delivery?")) return;
        await api("DELETE", `/api/deliveries/${b.dataset.deleteDelivery}`);
        toast("Delivery deleted");
        route();
      };
    });
  };
  form.place_id.addEventListener("change", showList);
  showList();

  form.onsubmit = async (e) => {
    e.preventDefault();
    const v = formData(form);
    const body = { place_id: v.place_id, date: v.date, pellet_id: v.pellet_id || null, notes: v.notes, cost: v.cost };
    body[mode] = v.amount;
    try {
      const saved = await api(d.id ? "PUT" : "POST", d.id ? `/api/deliveries/${d.id}` : "/api/deliveries", body);
      try { localStorage.setItem("lastPellet", v.pellet_id); } catch { /* ignore */ }
      toast(`${fmt(saved.kg, 0)} kg ${d.id ? "saved" : "added to storage"}`);
      go(`#/storage?place=${saved.place_id}`);
    } catch (err) {
      document.getElementById("form-error").textContent = err.message;
    }
  };
}

async function pelletsPage(params) {
  const pellets = await api("GET", "/api/pellets");
  const editId = params.get("edit");
  const p = pellets.find((x) => String(x.id) === editId) || {};
  app.innerHTML = `
    <div class="page-head"><div><h1>Pellets</h1><div class="muted">The pellet brands and bags you buy. Prices are stored on each entry when you log it, so changing a price later keeps your history intact.</div></div></div>
    <form class="card stack" id="pellet-form">
      <h2 class="full" style="margin:0">${p.id ? `Edit ${esc(p.brand)}` : "Add a pellet product"}</h2>
      ${inputField("brand", "Brand", p.brand, 'placeholder="e.g. ForestFire"', true)}
      ${inputField("name", "Product / type", p.name, 'placeholder="e.g. Premium 6 mm"')}
      <label class="field">Grade<select name="grade"><option value="">–</option>
        ${OPTIONS.pellet_grades.map((g) => `<option ${g === p.grade ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></label>
      ${inputField("bag_weight_kg", "Bag weight (kg)", p.bag_weight_kg ?? 15, 'type="number" step="0.1" min="0.1"', true)}
      ${inputField("price_per_bag", `Price per bag (${currency()})`, p.price_per_bag, 'type="number" step="0.01" min="0"')}
      ${inputField("notes", "Notes", p.notes, 'placeholder="shop, ash, quality…"')}
      <div class="actions full">
        <button class="primary" type="submit">${p.id ? "Save" : "Add pellet"}</button>
        ${p.id ? `<a class="btn" href="#/pellets">Cancel</a>` : ""}
        <span class="error" id="form-error"></span>
      </div>
    </form>
    ${pellets.length ? `<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Brand</th><th>Product</th><th>Grade</th><th class="num">Bag</th><th class="num">Price / bag</th><th class="num">Price / kg</th><th class="num">Used in</th><th></th></tr></thead>
      <tbody>${pellets.map((x) => `<tr><td>${esc(x.brand)}</td><td>${esc(x.name || "")}</td><td>${esc(x.grade || "")}</td>
        <td class="num">${fmt(x.bag_weight_kg, 1)} kg</td><td class="num">${money(x.price_per_bag)}</td><td class="num">${money(x.price_per_kg, 3)}</td>
        <td class="num">${x.entry_count} entries</td>
        <td><a class="btn link" href="#/pellets?edit=${x.id}">Edit</a><button class="link danger" data-delete="${x.id}" data-count="${x.entry_count}">Delete</button></td></tr>`).join("")}</tbody>
    </table></div></div>` : ""}`;
  document.getElementById("pellet-form").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api(p.id ? "PUT" : "POST", p.id ? `/api/pellets/${p.id}` : "/api/pellets", formData(e.target));
      toast(p.id ? "Pellet saved" : "Pellet added");
      p.id ? go("#/pellets") : route();
    } catch (err) {
      document.getElementById("form-error").textContent = err.message;
    }
  };
  document.querySelectorAll("[data-delete]").forEach((b) => {
    b.onclick = async () => {
      const n = Number(b.dataset.count);
      if (!confirm(n ? `Delete this pellet? Its ${n} entries keep their kg and cost.` : "Delete this pellet?")) return;
      await api("DELETE", `/api/pellets/${b.dataset.delete}`);
      toast("Pellet deleted");
      route();
    };
  });
}

function notFound() {
  app.innerHTML = `<div class="card empty"><p>That page does not exist.</p><a class="btn" href="#/">Back to overview</a></div>`;
}

// ---------- router ----------

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

async function route() {
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query || "");
  const parts = path.split("/").filter(Boolean);
  const section = parts[0] || "overview";
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === section));
  try {
    if (!OPTIONS) OPTIONS = await api("GET", "/api/options");
    if (section === "overview") await overviewPage(params);
    else if (section === "places" && !parts[1]) await placesPage();
    else if (section === "places" && parts[1] === "new") await placeFormPage(null);
    else if (section === "places" && parts[2] === "edit") await placeFormPage(parts[1]);
    else if (section === "places") await placeDetailPage(parts[1], params);
    else if (section === "pellets") await pelletsPage(params);
    else if (section === "storage") await storagePage(params);
    else if (section === "log") await logPage(parts[1], params);
    else notFound();
  } catch (err) {
    app.innerHTML = `<div class="card"><p class="error">${esc(err.message)}</p><a class="btn" href="#/">Back to overview</a></div>`;
  }
  if (path !== route.lastPath) window.scrollTo(0, 0);
  route.lastPath = path;
}

const currencyInput = document.getElementById("currency");
currencyInput.value = currency();
currencyInput.onchange = () => {
  try { localStorage.setItem("currency", currencyInput.value.trim() || "€"); } catch { /* ignore */ }
  route();
};
window.addEventListener("hashchange", route);
route();
