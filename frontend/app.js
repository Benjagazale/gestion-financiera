/* Agente Financiero — SPA vanilla sobre la API (envelope {data|error}). */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let clave = localStorage.getItem("api_key") || "";
let categorias = [];
let borrador = null; // { draft, crid } pendiente de confirmar
let listaCache = {}; // id -> transacción (para editar sin re-fetch)
let editId = null;   // id en edición en el formulario manual
let vistaMov = localStorage.getItem("vista_mov") || "agrupado"; // "agrupado" | "lista"

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
    .map((c) => `<option value="${c.id}">${iconoCategoria(c.id)} ${esc(c.name)}</option>`)
    .join("");
  $("#filtro-cat").innerHTML = '<option value="">Todas las categorías</option>' + opciones;
  for (const inst of Object.values(REGISTROS)) {
    inst.r["f-cat"].innerHTML = opciones;
    inst.r["b-cat"].innerHTML = opciones;
  }
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
      <span class="barra-nombre">${iconoCategoria(f.category_id)} ${esc(f.category_name)}<span class="barra-meta">${f.count} op.</span></span>
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
  ul.className = "lista";
  if (!nuevos.length) {
    ul.innerHTML = '<li class="vacio">Sin movimientos en este período.</li>';
    return;
  }
  if (vistaMov === "agrupado") renderAgrupado(ul, nuevos);
  else renderFilas(ul, nuevos);
}

function nombresCategorias() {
  const nombres = {};
  categorias.forEach((c) => (nombres[c.id] = c.name));
  return nombres;
}

function filaItem(t, nombres) {
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
          <div class="item-meta">${fechaLinda(t.transaction_date)} · ${iconoCategoria(t.category_id)} ${esc(cat)}${
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
  return li;
}

function renderFilas(ul, items) {
  const nombres = nombresCategorias();
  ul.innerHTML = "";
  for (const t of items) ul.appendChild(filaItem(t, nombres));
}

// Vista agrupada: columnas por categoría (kanban horizontal), ordenadas
// por monto total absoluto; agrupación100% client-side por category_id.
function renderAgrupado(ul, items) {
  const nombres = nombresCategorias();
  const grupos = new Map();
  for (const t of items) {
    const id = t.category_id ?? null;
    if (!grupos.has(id)) grupos.set(id, []);
    grupos.get(id).push(t);
  }
  const columnas = [...grupos.entries()]
    .map(([id, filas]) => {
      const total = filas.reduce(
        (s, t) =>
          s + (t.amount_clp != null ? t.amount_clp : t.amount) * (t.type === "gasto" ? -1 : 1),
        0
      );
      return { id, nombre: nombres[id] || "Sin Categorizar", filas, total };
    })
    .sort((a, b) => Math.abs(b.total) - Math.abs(a.total) || a.nombre.localeCompare(b.nombre));

  ul.className = "lista agrupada";
  ul.innerHTML = columnas
    .map(
      (col) => `
    <li class="columna">
      <div class="col-cab">
        <span class="col-titulo">${iconoCategoria(col.id)} ${esc(col.nombre)}<span class="col-count">${col.filas.length}</span></span>
        <span class="col-total">${fmtCLP.format(Math.abs(col.total))}</span>
      </div>
      <ul class="lista-int"></ul>
    </li>`
    )
    .join("");
  const contenedores = ul.querySelectorAll(".lista-int");
  columnas.forEach((col, i) => {
    for (const t of col.filas) contenedores[i].appendChild(filaItem(t, nombres));
  });
}

async function refrescar() {
  await Promise.all([cargarResumen(), cargarLista(), cargarPorCategoria()]);
}

// ---------------------------------------------------------------- Borrador IA (por instancia)

async function analizar(ev) {
  const inst = instanciaDe(ev.currentTarget);
  if (!inst) return;
  const texto = inst.r.texto.value.trim();
  if (!texto) return;
  const btn = inst.r.analizar;
  btn.disabled = true;
  btn.textContent = "Analizando…";
  try {
    const r = await api("/transactions/parse", { method: "POST", body: { text: texto } });
    borrador = { draft: r.draft, crid: crypto.randomUUID(), prefijo: inst.prefijo }; // mismo crid en reintentos → idempotente
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
  const inst = REGISTROS[borrador.prefijo];
  if (!inst) return;
  inst.r["b-tipo"].value = d.type;
  inst.r["b-monto"].value = d.amount;
  inst.r["b-moneda"].value = d.currency;
  inst.r["b-cat"].value = String(d.category_id);
  inst.r["b-fecha"].value = d.transaction_date;
  inst.r["b-desc"].value = d.description || "";
  inst.r.borrador.classList.remove("oculto");
  inst.r.borrador.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function confirmarBorrador(ev) {
  ev.preventDefault();
  if (!borrador) return;
  const inst = instanciaDe(ev.currentTarget);
  if (!inst) return;
  const btn = inst.r.confirmar;
  btn.disabled = true;
  try {
    await api("/transactions/confirm", {
      method: "POST",
      body: {
        type: inst.r["b-tipo"].value,
        amount: parseFloat(inst.r["b-monto"].value),
        currency: inst.r["b-moneda"].value,
        category_id: parseInt(inst.r["b-cat"].value, 10),
        merchant: borrador.draft.merchant || null,
        description: inst.r["b-desc"].value.trim() || null,
        transaction_date: inst.r["b-fecha"].value,
        client_request_id: borrador.crid, // mismo id en reintentos → idempotente
      },
    });
    toast("Movimiento registrado ✓");
    inst.r.texto.value = "";
    cerrarBorrador();
    await cargarVista(tabActual);
  } catch (err) {
    toast(err.message || "Error al confirmar", true);
  } finally {
    btn.disabled = false;
  }
}

function cerrarBorrador() {
  if (borrador) {
    const inst = REGISTROS[borrador.prefijo];
    if (inst) inst.r.borrador.classList.add("oculto");
  }
  borrador = null;
}

// ---------------------------------------------------------------- Registro (factory)
// Panel "Registro rápido + Alta manual": una sola fuente de markup en JS,
// instanciada en Resumen / Ingresos / Gastos. Sin IDs duplicados:
// el HTML solo aporta slots (data-slot) y el markup usa data-role.

const REGISTROS = {}; // prefijo -> { prefijo, tipo, r: {data-role -> nodo} }

function instanciaDe(el) {
  const sec = el.closest("[data-registro]");
  return sec ? REGISTROS[sec.dataset.registro] : null;
}

function crearPanelRegistro({ prefijo, tipo = "" }) {
  const sel = tipo || "gasto"; // tipo por defecto del formulario manual

  const rapido = document.createElement("section");
  rapido.className = "panel";
  rapido.dataset.registro = prefijo;
  rapido.innerHTML = `
    <h2>Registro rápido ✨</h2>
    <textarea data-role="texto" rows="2"
      placeholder="Ej: Pagué 4500 en la micro al trabajo"></textarea>
    <button data-role="analizar" class="primario">Analizar</button>
    <div data-role="borrador" class="borrador oculto">
      <h3>Borrador — ajusta lo que haga falta y confirma</h3>
      <form data-role="form-borrador" class="form-borrador">
        <label class="ancho">Descripción
          <input type="text" data-role="b-desc" maxlength="2000" placeholder="Opcional">
        </label>
        <label>Tipo
          <select data-role="b-tipo">
            <option value="gasto">Gasto</option>
            <option value="ingreso">Ingreso</option>
          </select>
        </label>
        <label>Monto
          <input type="number" data-role="b-monto" step="0.01" min="0.01" required>
        </label>
        <label>Moneda
          <select data-role="b-moneda"><option>CLP</option><option>USD</option></select>
        </label>
        <label>Categoría
          <select data-role="b-cat"></select>
        </label>
        <label>Fecha
          <input type="date" data-role="b-fecha" required>
        </label>
        <div class="fila ancho">
          <button type="submit" data-role="confirmar" class="exito">Confirmar ✓</button>
          <button type="button" data-role="descartar">Descartar</button>
        </div>
      </form>
    </div>`;

  const manual = document.createElement("section");
  manual.className = "panel";
  manual.dataset.registro = prefijo;
  manual.innerHTML = `
    <div class="cabecera">
      <h2 data-role="titulo">Alta manual</h2>
      <button type="button" data-role="cancelar" class="oculto">Cancelar edición</button>
    </div>
    <form data-role="form-manual" class="form">
      <label>Tipo
        <select data-role="f-tipo">
          <option value="gasto"${sel === "gasto" ? " selected" : ""}>Gasto</option>
          <option value="ingreso"${sel === "ingreso" ? " selected" : ""}>Ingreso</option>
        </select>
      </label>
      <label>Monto
        <input type="number" data-role="f-monto" step="0.01" min="0.01" required placeholder="0">
      </label>
      <label>Moneda
        <select data-role="f-moneda"><option>CLP</option><option>USD</option></select>
      </label>
      <label>Categoría
        <select data-role="f-cat"></select>
      </label>
      <label>Fecha
        <input type="date" data-role="f-fecha" required>
      </label>
      <label class="ancho">Descripción
        <input type="text" data-role="f-desc" maxlength="2000" placeholder="Opcional">
      </label>
      <div class="ancho">
        <button type="submit" data-role="guardar" class="primario">Guardar</button>
      </div>
    </form>`;

  const slotRapido = document.querySelector(`[data-slot="${prefijo}-rapido"]`);
  const slotManual = document.querySelector(`[data-slot="${prefijo}-manual"]`);
  if (!slotRapido || !slotManual) return null;

  // El span (columnas del grid) lo decide el slot en el HTML
  for (const [panel, slot] of [[rapido, slotRapido], [manual, slotManual]]) {
    const span = [...slot.classList].filter((c) => c.startsWith("span-"));
    if (span.length) panel.classList.add(...span);
    slot.replaceWith(panel);
  }

  const inst = { prefijo, tipo, r: {} };
  for (const panel of [rapido, manual]) {
    panel.querySelectorAll("[data-role]").forEach((n) => (inst.r[n.dataset.role] = n));
  }
  inst.r.analizar.addEventListener("click", analizar);
  inst.r["form-borrador"].addEventListener("submit", confirmarBorrador);
  inst.r.descartar.addEventListener("click", cerrarBorrador);
  inst.r["form-manual"].addEventListener("submit", guardarManual);
  inst.r.cancelar.addEventListener("click", cancelarEdicion);
  inst.r["f-fecha"].value = hoyLocal().dia;

  REGISTROS[prefijo] = inst;
  return inst;
}

function montarRegistros() {
  crearPanelRegistro({ prefijo: "resumen" });
  crearPanelRegistro({ prefijo: "ingresos", tipo: "ingreso" });
  crearPanelRegistro({ prefijo: "gastos", tipo: "gasto" });
}

// ---------------------------------------------------------------- Manual / edición
// La edición usa el panel de la pestaña activa: las listas solo existen en
// resumen/ingresos/gastos, que son justamente las pestañas con registro.

function editar(id) {
  const t = listaCache[id];
  const inst = REGISTROS[tabActual];
  if (!t || !inst) return;
  editId = id;
  inst.r.titulo.textContent = `Editar transacción #${id}`;
  inst.r.cancelar.classList.remove("oculto");
  inst.r["f-tipo"].value = t.type;
  inst.r["f-monto"].value = t.amount;
  inst.r["f-moneda"].value = t.currency;
  inst.r["f-cat"].value = t.category_id || "";
  inst.r["f-fecha"].value = t.transaction_date;
  inst.r["f-desc"].value = t.description || "";
  inst.r["form-manual"].scrollIntoView({ behavior: "smooth" });
}

function cancelarEdicion() {
  editId = null;
  // Resetea las 3 instancias; el `selected` del markup restaura el tipo por defecto
  for (const inst of Object.values(REGISTROS)) {
    inst.r.titulo.textContent = "Alta manual";
    inst.r.cancelar.classList.add("oculto");
    inst.r["form-manual"].reset();
    inst.r["f-fecha"].value = hoyLocal().dia;
  }
}

async function guardarManual(ev) {
  ev.preventDefault();
  const form = ev.currentTarget;
  const inst = instanciaDe(form);
  if (!inst) return;
  const btn = inst.r.guardar;
  btn.disabled = true;
  const payload = {
    type: inst.r["f-tipo"].value,
    amount: parseFloat(inst.r["f-monto"].value),
    currency: inst.r["f-moneda"].value,
    category_id: inst.r["f-cat"].value ? parseInt(inst.r["f-cat"].value) : null,
    description: inst.r["f-desc"].value.trim() || null,
    transaction_date: inst.r["f-fecha"].value,
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
      form.reset();
      inst.r["f-fecha"].value = hoyLocal().dia;
    }
    await cargarVista(tabActual);
  } catch (err) {
    toast(err.message || "Error al guardar", true);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- Listas: editar/eliminar
// Delegación sobre #app: funciona en las3 listas y en los3 toggles de vista

function sincronizarToggle() {
  $$(".toggle [data-vista]").forEach((b) => {
    const activo = b.dataset.vista === vistaMov;
    b.classList.toggle("activo", activo);
    b.setAttribute("aria-pressed", String(activo));
  });
}

async function onAppClick(ev) {
  const btn = ev.target.closest("button");
  if (!btn || !btn.dataset) return;
  if (btn.dataset.vista) {
    vistaMov = btn.dataset.vista === "lista" ? "lista" : "agrupado";
    localStorage.setItem("vista_mov", vistaMov);
    sincronizarToggle();
    await cargarVista(tabActual); // re-renderiza la lista visible
    return;
  }
  if (!btn.dataset.edit && !btn.dataset.del) return;
  if (btn.dataset.edit) {
    editar(parseInt(btn.dataset.edit, 10));
  } else if (btn.dataset.del) {
    if (!confirm("¿Eliminar esta transacción?")) return;
    try {
      await api("/transactions/" + btn.dataset.del, { method: "DELETE" });
      toast("Transacción eliminada ✓");
      if (editId === parseInt(btn.dataset.del, 10)) cancelarEdicion();
      await cargarVista(tabActual); // refresca la pestaña visible (resumen/ingresos/gastos)
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
  montarRegistros(); //3 paneles de registro (Resumen / Ingresos / Gastos)
  sincronizarToggle(); // estado del toggle [Por categoría | Lista]
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
// Registro rápido / alta manual: listeners por instancia (crearPanelRegistro)
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
