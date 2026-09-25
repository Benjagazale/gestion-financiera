/* Agente Financiero — SPA vanilla sobre la API (envelope {data|error}). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let clave = localStorage.getItem("api_key") || "";
let categorias = [];
let borrador = null; // { draft, crid } pendiente de confirmar
let listaCache = {}; // id -> transacción (para editar sin re-fetch)
let editId = null;   // id en edición en el formulario manual

// Pestañas (hash routing: #resumen, #ingresos, …) — sin framework
const VISTAS = ["resumen", "ingresos", "gastos", "ahorros", "cuentas", "presupuestos", "metas"];
let tabActual = "resumen";

const fmtCLP = new Intl.NumberFormat("es-CL", {
  style: "currency", currency: "CLP", maximumFractionDigits: 0,
});

function hoyLocal() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return {
    mes: `${d.getFullYear()}-${p(d.getMonth() + 1)}`,
    dia: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
  };
}

function fechaLinda(iso) {
  return new Date(iso + "T12:00:00").toLocaleDateString("es-CL", {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// Período activo (selector de mes): null = sin filtro (todo)
function rangoMes() {
  const valor = $("#mes").value;
  if (!valor) return null;
  const [a, m] = valor.split("-").map(Number);
  const ultimo = new Date(a, m, 0).getDate();
  return { from: `${valor}-01`, to: `${valor}-${String(ultimo).padStart(2, "0")}` };
}

function etiquetaPeriodo() {
  const valor = $("#mes").value;
  if (!valor) return "todos los períodos";
  const [a, m] = valor.split("-").map(Number);
  return new Date(a, m - 1, 1).toLocaleDateString("es-CL", { month: "long", year: "numeric" });
}

// ---------------------------------------------------------------- API

async function api(ruta, { method = "GET", body } = {}) {
  const enc = { method, headers: { "X-API-Key": clave } };
  if (body !== undefined) {
    enc.headers["Content-Type"] = "application/json";
    enc.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(ruta, enc);
  } catch {
    throw {
      code: "SIN_CONEXION",
      message: "No se pudo contactar al servidor. Si acaba de despertar, espera ~1 min y reintenta.",
    };
  }
  let datos = null;
  try { datos = await resp.json(); } catch (_) { /* sin cuerpo */ }
  if (!resp.ok) {
    if (resp.status === 401) {
      clave = "";
      localStorage.removeItem("api_key");
      mostrarSetup("La API key fue rechazada. Pégala de nuevo.");
    }
    throw (datos && datos.error) || { code: "HTTP_" + resp.status, message: "Error " + resp.status };
  }
  return datos ? datos.data : null;
}

function toast(msg, esError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (esError ? " error" : "");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("oculto"), esError ? 5000 : 2500);
}

// ---------------------------------------------------------------- UI básica

function mostrarSetup(msg = "") {
  $("#setup").classList.remove("oculto");
  $("#app").classList.add("oculto");
  $("#setup-msg").textContent = msg;
  $("#estado").textContent = "Sin conexión";
}

function mostrarApp() {
  $("#setup").classList.add("oculto");
  $("#app").classList.remove("oculto");
  $("#estado").textContent = "Conectado ✓";
}

// ---------------------------------------------------------------- Pestañas

function tabDeHash() {
  const h = location.hash.replace("#", "");
  return VISTAS.includes(h) ? h : "resumen";
}

async function seleccionarTab(id) {
  tabActual = id;
  $$(".vista").forEach((v) => v.classList.toggle("oculto", v.id !== "vista-" + id));
  $$(".tab").forEach((t) => {
    const activa = t.dataset.tab === id;
    t.classList.toggle("activa", activa);
    t.setAttribute("aria-selected", String(activa));
  });
  if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
  await cargarVista(id);
}

async function cargarVista(id) {
  try {
    if (id === "resumen") await refrescar();
    else if (id === "ingresos") await cargarVistaTipo("ingreso");
    else if (id === "gastos") await cargarVistaTipo("gasto");
    // ahorros / cuentas / presupuestos / metas: paneles "próximamente" (sin carga)
  } catch (err) {
    toast(err.message || "Error cargando datos", true);
  }
}

// ---------------------------------------------------------------- Carga

async function cargarCategorias() {
  categorias = await api("/categories");
  const opciones = categorias
    .map((c) => `<option value="${c.id}">${esc(c.name)}</option>`)
    .join("");
  $("#f-cat").innerHTML = opciones;
  $("#b-cat").innerHTML = opciones;
  $("#filtro-cat").innerHTML = '<option value="">Todas las categorías</option>' + opciones;
}

async function cargarResumen() {
  const rango = rangoMes();
  const qs = rango ? "?" + new URLSearchParams(rango) : "";
  const r = await api("/transactions/summary" + qs);
  $("#ingresos").textContent = fmtCLP.format(r.income);
  $("#gastos").textContent = fmtCLP.format(r.expenses);
  const balance = $("#balance");
  balance.textContent = fmtCLP.format(r.balance);
  balance.className = r.balance < 0 ? "neg" : "";
}

async function cargarPorCategoria() {
  const params = new URLSearchParams({ type: "gasto" });
  const rango = rangoMes();
  if (rango) {
    params.set("from", rango.from);
    params.set("to", rango.to);
  }
  const filas = await api("/transactions/summary/by-category?" + params);
  $("#cat-periodo").textContent = etiquetaPeriodo();
  renderBarras($("#barras"), filas);
}

function renderBarras(cont, filas) {
  cont.innerHTML = "";
  if (!filas.length) {
    cont.innerHTML = '<p class="vacio">Sin movimientos en este período.</p>';
    return;
  }
  const top = filas.slice(0, 8);
  const max = top[0].total;
  for (const f of top) {
    const fila = document.createElement("div");
    fila.className = "barra-fila";
    const pct = Math.max(4, Math.round((f.total / max) * 100));
    fila.innerHTML = `
      <span class="barra-nombre">${esc(f.category_name)}<span class="barra-meta">${f.count} op.</span></span>
      <strong>${fmtCLP.format(f.total)}</strong>
      <span class="barra-track"><span class="barra-fill" style="width:${pct}%"></span></span>`;
    cont.appendChild(fila);
  }
}

// Pestañas Ingresos / Gastos: KPI + barras + lista filtrados por tipo
async function cargarVistaTipo(tipo) {
  const pref = tipo === "gasto" ? "gastos" : "ingresos";
  const rango = rangoMes();

  const qsResumen = rango ? "?" + new URLSearchParams(rango) : "";
  const paramsBarras = new URLSearchParams({ type: tipo });
  const paramsLista = new URLSearchParams({ type: tipo, limit: "100", skip: "0" });
  if (rango) {
    paramsBarras.set("from", rango.from);
    paramsBarras.set("to", rango.to);
    paramsLista.set("from", rango.from);
    paramsLista.set("to", rango.to);
  }

  const [resumen, barras, items] = await Promise.all([
    api("/transactions/summary" + qsResumen),
    api("/transactions/summary/by-category?" + paramsBarras),
    api("/transactions?" + paramsLista),
  ]);

  const monto = tipo === "gasto" ? resumen.expenses : resumen.income;
  $("#kpi-" + pref).textContent = fmtCLP.format(monto);
  $("#kpi-" + pref + "-sub").textContent = etiquetaPeriodo();
  renderBarras($("#barras-" + pref), barras);
  renderLista($("#lista-" + pref), items);
}

async function cargarLista() {
  const params = new URLSearchParams({ limit: "100", skip: "0" });
  const rango = rangoMes();
  if (rango) {
    params.set("from", rango.from);
    params.set("to", rango.to);
  }
  const t = $("#filtro-tipo").value;
  if (t) params.set("type", t);
  const c = $("#filtro-cat").value;
  if (c) params.set("category_id", c);
  const items = await api("/transactions?" + params);
  renderLista($("#lista"), items);
}

function renderLista(ul, items) {
  const nuevos = [...items].reverse();
  nuevos.forEach((t) => (listaCache[t.id] = t));

  if (!nuevos.length) {
    ul.innerHTML = '<li class="vacio">Sin movimientos en este período.</li>';
    return;
  }

  const nombres = {};
  categorias.forEach((c) => (nombres[c.id] = c.name));

  ul.innerHTML = "";
  for (const t of nuevos) {
    const cat = nombres[t.category_id] || "—";
    const monto =
      t.currency === "USD" && t.amount_clp != null
        ? `US$ ${Number(t.amount).toLocaleString("es-CL")} → ${fmtCLP.format(t.amount_clp)}`
        : fmtCLP.format(t.amount_clp != null ? t.amount_clp : t.amount);
    const li = document.createElement("li");
    li.className = "item " + t.type;
    li.innerHTML = `
      <div class="item-izq">
        <span class="badge">${t.type === "gasto" ? "Gasto" : "Ingreso"}</span>
        <div>
          <div class="item-desc">${esc(t.description || cat)}</div>
          <div class="item-meta">${fechaLinda(t.transaction_date)} · ${esc(cat)}${
            t.merchant ? " · " + esc(t.merchant) : ""
          }</div>
        </div>
      </div>
      <div class="item-der">
        <strong class="${t.type}">${t.type === "gasto" ? "−" : "+"}${monto}</strong>
        <span class="acciones">
          <button type="button" title="Editar" data-edit="${t.id}">✏️</button>
          <button type="button" title="Eliminar" data-del="${t.id}">🗑️</button>
        </span>
      </div>`;
    ul.appendChild(li);
  }
}

async function refrescar() {
  await Promise.all([cargarResumen(), cargarLista(), cargarPorCategoria()]);
}

// ---------------------------------------------------------------- Borrador IA

async function analizar() {
  const texto = $("#texto-ia").value.trim();
  if (!texto) return;
  const btn = $("#btn-analizar");
  btn.disabled = true;
  btn.textContent = "Analizando…";
  try {
    const r = await api("/transactions/parse", { method: "POST", body: { text: texto } });
    borrador = { draft: r.draft, crid: crypto.randomUUID() }; // mismo crid en reintentos → idempotente
    renderBorrador();
  } catch (err) {
    toast(err.message || "Error al analizar", true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Analizar";
  }
}

function renderBorrador() {
  const d = borrador.draft;
  $("#b-tipo").value = d.type;
  $("#b-monto").value = d.amount;
  $("#b-moneda").value = d.currency;
  $("#b-cat").value = String(d.category_id);
  $("#b-fecha").value = d.transaction_date;
  $("#b-desc").value = d.description || "";
  $("#borrador").classList.remove("oculto");
  $("#borrador").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function confirmarBorrador(ev) {
  ev.preventDefault();
  if (!borrador) return;
  const btn = $("#btn-confirmar");
  btn.disabled = true;
  try {
    await api("/transactions/confirm", {
      method: "POST",
      body: {
        type: $("#b-tipo").value,
        amount: parseFloat($("#b-monto").value),
        currency: $("#b-moneda").value,
        category_id: parseInt($("#b-cat").value, 10),
        merchant: borrador.draft.merchant || null,
        description: $("#b-desc").value.trim() || null,
        transaction_date: $("#b-fecha").value,
        client_request_id: borrador.crid, // mismo id en reintentos → idempotente
      },
    });
    toast("Movimiento registrado ✓");
    cerrarBorrador();
    $("#texto-ia").value = "";
    await refrescar();
  } catch (err) {
    toast(err.message || "Error al confirmar", true);
  } finally {
    btn.disabled = false;
  }
}

function cerrarBorrador() {
  borrador = null;
  $("#borrador").classList.add("oculto");
}

// ---------------------------------------------------------------- Manual / edición

function editar(id) {
  const t = listaCache[id];
  if (!t) return;
  editId = id;
  $("#form-titulo").textContent = `Editar transacción #${id}`;
  $("#btn-cancelar-edicion").classList.remove("oculto");
  $("#f-tipo").value = t.type;
  $("#f-monto").value = t.amount;
  $("#f-moneda").value = t.currency;
  $("#f-cat").value = t.category_id || "";
  $("#f-fecha").value = t.transaction_date;
  $("#f-desc").value = t.description || "";
  $("#form-manual").scrollIntoView({ behavior: "smooth" });
}

function cancelarEdicion() {
  editId = null;
  $("#form-titulo").textContent = "Alta manual";
  $("#btn-cancelar-edicion").classList.add("oculto");
  $("#form-manual").reset();
  $("#f-fecha").value = hoyLocal().dia;
}

async function guardarManual(ev) {
  ev.preventDefault();
  const btn = $("#btn-guardar");
  btn.disabled = true;
  const payload = {
    type: $("#f-tipo").value,
    amount: parseFloat($("#f-monto").value),
    currency: $("#f-moneda").value,
    category_id: $("#f-cat").value ? parseInt($("#f-cat").value) : null,
    description: $("#f-desc").value.trim() || null,
    transaction_date: $("#f-fecha").value,
  };
  try {
    if (editId) {
      await api("/transactions/" + editId, { method: "PUT", body: payload });
      toast("Transacción actualizada ✓");
      cancelarEdicion();
    } else {
      payload.client_request_id = crypto.randomUUID();
      await api("/transactions", { method: "POST", body: payload });
      toast("Transacción guardada ✓");
      $("#form-manual").reset();
      $("#f-fecha").value = hoyLocal().dia;
    }
    await refrescar();
  } catch (err) {
    toast(err.message || "Error al guardar", true);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- Listas: editar/eliminar
// Delegación sobre #app: funciona en las 3 listas (resumen/ingresos/gastos)

async function onAppClick(ev) {
  const btn = ev.target.closest("button");
  if (!btn || !btn.dataset || (!btn.dataset.edit && !btn.dataset.del)) return;
  if (btn.dataset.edit) {
    editar(parseInt(btn.dataset.edit, 10));
  } else if (btn.dataset.del) {
    if (!confirm("¿Eliminar esta transacción?")) return;
    try {
      await api("/transactions/" + btn.dataset.del, { method: "DELETE" });
      toast("Transacción eliminada ✓");
      if (editId === parseInt(btn.dataset.del, 10)) cancelarEdicion();
      await refrescar();
      if (tabActual === "ingresos" || tabActual === "gastos") await cargarVista(tabActual);
    } catch (err) {
      toast(err.message || "Error al eliminar", true);
    }
  }
}

// ---------------------------------------------------------------- Conexión / setup

async function conectar() {
  clave = $("#clave-input").value.trim();
  if (!clave) {
    $("#setup-msg").textContent = "Pega tu API key para continuar.";
    return;
  }
  const btn = $("#btn-conectar");
  btn.disabled = true;
  try {
    await api("/categories"); // valida la clave
    localStorage.setItem("api_key", clave);
    await arrancar();
  } catch (err) {
    if (clave) $("#setup-msg").textContent = err.message || "No se pudo validar la key.";
  } finally {
    btn.disabled = false;
  }
}

async function arrancar() {
  try {
    await cargarCategorias();
  } catch (err) {
    if (!clave) return; // 401 ya mostró el setup
    mostrarApp();
    toast(err.message || "Error cargando categorías", true);
    await seleccionarTab(tabDeHash());
    return;
  }
  mostrarApp();
  await seleccionarTab(tabDeHash());
}

async function iniciar() {
  $("#f-fecha").value = hoyLocal().dia;
  $("#mes").value = hoyLocal().mes;
  $("#estado").textContent = "Conectando…";

  // Ping sin API key: despierta el servicio si está durmiendo (máx 90 s)
  const ctrl = new AbortController();
  const reloj = setTimeout(() => ctrl.abort(), 90000);
  try {
    await fetch("/health", { signal: ctrl.signal });
  } catch {
    $("#estado").textContent = "Servidor durmiendo, reintenta";
  } finally {
    clearTimeout(reloj);
  }

  if (!clave) {
    mostrarSetup();
    return;
  }
  await arrancar();
}

// ---------------------------------------------------------------- Eventos

$("#btn-conectar").addEventListener("click", conectar);
$("#clave-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") conectar();
});
$("#btn-analizar").addEventListener("click", analizar);
$("#form-borrador").addEventListener("submit", confirmarBorrador);
$("#btn-descartar").addEventListener("click", cerrarBorrador);
$("#form-manual").addEventListener("submit", guardarManual);
$("#btn-cancelar-edicion").addEventListener("click", cancelarEdicion);
$("#app").addEventListener("click", onAppClick);
$("#mes").addEventListener("change", () => {
  cargarVista(tabActual).catch((e) => toast(e.message, true));
});
$("#filtro-tipo").addEventListener("change", () => cargarLista().catch((e) => toast(e.message, true)));
$("#filtro-cat").addEventListener("change", () => cargarLista().catch((e) => toast(e.message, true)));
window.addEventListener("hashchange", () => {
  const h = tabDeHash();
  if (h !== tabActual) seleccionarTab(h);
});

iniciar();
