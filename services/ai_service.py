"""
Servicio de IA (Groq) — extracción estructurada de transacciones.

Resiliencia:
- Timeout explícito por llamada (15s) para no colgar requests (límite ~100s en Render).
- Fallback de modelo: gpt-oss-120b → gpt-oss-20b.
- Validación de la salida contra un schema Pydantic + 1 intento de "reparo"
  si el modelo devuelve JSON inválido o datos fuera de contrato.
- Categorías inyectadas desde la BD en el prompt (nunca hardcodeadas).
"""
import json
import logging
import os
from typing import Literal, Optional

from core.config import settings
from groq import Groq
from pydantic import BaseModel, PositiveFloat, ValidationError

logger = logging.getLogger("agente")

# Orden de preferencia: primario → fallback
MODELOS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
TIMEOUT_SEGUNDOS = 15.0
MAX_INTENTOS_POR_MODELO = 2  # 1 llamada + 1 reparo

_client = Groq(
    api_key=settings.groq_api_key,
    timeout=TIMEOUT_SEGUNDOS,
    max_retries=0,  # los reintentos los gestionamos nosotros (fallback de modelo)
)


class AIServiceError(Exception):
    """La IA falló tras agotar modelos/intentos. El endpoint la traduce a 503."""


class TransactionExtraction(BaseModel):
    """Contrato estricto de lo que la IA debe devolver."""

    type: Literal["gasto", "ingreso"]
    amount: PositiveFloat
    currency: str = "CLP"
    merchant: Optional[str] = None
    category_id: Optional[int] = None
    category: Optional[str] = None
    description: Optional[str] = None


def _prompt_sistema(categorias: Optional[list[dict]] = None) -> str:
    if categorias:
        lista = ", ".join(f"{c['id']}={c['name']}" for c in categorias)
    else:
        lista = "ninguna disponible"
    return (
        "Eres un asistente financiero experto. Extrae la información de la transacción "
        "y respóndela estrictamente en formato JSON con estas claves exactas:\n"
        '- "type": obligatorio, SOLO "gasto" o "ingreso" (español, minúsculas)\n'
        '- "amount": obligatorio, número POSITIVO sin símbolos ni separadores\n'
        '- "currency": "CLP" por defecto (usa "USD" solo si el texto lo indica)\n'
        '- "merchant": string o null (local o comercio mencionado)\n'
        f'- "category_id": entero o null (categorías conocidas: {lista})\n'
        '- "category": nombre de categoría o null (si no encaja en los IDs)\n'
        '- "description": string corto y descriptivo en español\n'
        "No incluyas ningún texto fuera del JSON."
    )


def _llamar(model: str, messages: list[dict]) -> str:
    completion = _client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    content = completion.choices[0].message.content
    if not content:
        raise AIServiceError("El modelo devolvió una respuesta vacía")
    return content


def parse_transaction_with_ai(text: str, categorias: Optional[list[dict]] = None) -> str:
    """
    Extrae una transacción estructurada del texto libre.

    Retorna el JSON validado como string (contrato histórico de los endpoints).
    Lanza AIServiceError si todos los modelos/intentos fallan.
    """
    mensajes: list[dict] = [
        {"role": "system", "content": _prompt_sistema(categorias)},
        {"role": "user", "content": text},
    ]
    ultimo_error: Optional[Exception] = None

    for model in MODELOS:
        for intento in range(MAX_INTENTOS_POR_MODELO):
            try:
                bruto = _llamar(model, mensajes)
            except Exception as e:  # timeout, 429, 5xx, respuesta vacía → siguiente modelo
                logger.warning("Modelo %s no respondió (intento %d): %s", model, intento + 1, e)
                ultimo_error = e
                break

            try:
                datos = TransactionExtraction(**json.loads(bruto))
                return datos.model_dump_json()
            except (json.JSONDecodeError, ValidationError, TypeError) as e:
                # Reparo: pedimos al modelo corregir su propia salida una vez
                logger.warning("Salida inválida (modelo=%s, intento=%d): %s", model, intento + 1, e)
                ultimo_error = e
                mensajes = mensajes + [
                    {
                        "role": "user",
                        "content": (
                            f"Tu respuesta anterior no fue válida ({e}). "
                            "Devuelve SOLO el JSON corregido. "
                            f"Respuesta previa: {bruto[:1000]}"
                        ),
                    }
                ]
                continue

    raise AIServiceError(
        f"No se pudo extraer la transacción tras probar {len(MODELOS)} modelos. "
        f"Último error: {ultimo_error}"
    )
