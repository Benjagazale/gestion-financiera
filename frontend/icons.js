/* Agente Financiero — mapa de íconos por categoría (id de Supabase → emoji).
 *
 * Contrato: al crear una categoría NUEVA en la base, agregar UNA línea aquí.
 * Categoría sin ícono asignado (o id desconocido/null) → 📦 (default).
 * Cargado antes de app.js: script clásico, sin build ni módulos.
 */
"use strict";

const ICONOS_CATEGORIA = {
  1: "🥙",  // Alimentación
  2: "🚗",  // Transporte
  3: "🎬",  // Ocio y Entretenimiento
  4: "🏠",  // Hogar
  5: "🥬",  // Feria
  6: "🛒",  // Supermercado
  7: "⚽",  // Deporte
  8: "🏥",  // Salud
  9: "📺",  // Suscripciones
  10: "💡", // Servicios
  11: "💳", // Deudas
  12: "💼", // Sueldo y Salario
  13: "💻", // Freelance / Trabajos Extra
  14: "🎁", // Regalos y Premios
  15: "📈", // Inversiones y Rendimientos
  16: "💰", // Otros Ingresos
  17: "📦", // Sin Categorizar (también es el default)
};

const ICONO_POR_DEFECTO = "📦";

/** Ícono representativo de una categoría (acepta id o null). */
function iconoCategoria(id) {
  return ICONOS_CATEGORIA[id] || ICONO_POR_DEFECTO;
}
