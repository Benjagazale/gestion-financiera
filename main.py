from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
from gemini_service import procesar_mensaje_con_gemini
import json

app = FastAPI(title="Agente Financiero API", version="1.0")

@app.get("/categories")
def listar_categorias(db: Session = Depends(get_db)):
    return db.query(models.Category).all()

@app.post("/transactions/process")
def procesar_y_guardar_transaccion(mensaje: str, db: Session = Depends(get_db)):
    try:
        # Intentamos procesar con la IA (que ya incluye reintentos)
        resultado_json_str = procesar_mensaje_con_gemini(mensaje)
        datos_transaccion = json.loads(resultado_json_str)

        nueva_transaccion = models.Transaction(
            user_id=1, # ID temporal por defecto.
            type=datos_transaccion.get("type"),
            amount=datos_transaccion.get("amount"),
            currency=datos_transaccion.get("currency", "CLP"),
            merchant=datos_transaccion.get("merchant"),
            category_id=datos_transaccion.get("category_id"),
            description=datos_transaccion.get("description")
        )

        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)

        return {
            "status": "success",
            "message": "Transacción procesada y guardada con éxito por la IA.",
            "data": nueva_transaccion
        }
    
    except Exception as e:
        db.rollback()
        # Capa de Respaldo (Fallback): Si la IA no responde, devolvemos guía y las categorías
        categorias = db.query(models.Category).all()
        return {
            "status": "fallback_required",
            "message": "Los servidores de IA están ocupados temporalmente. Por favor, utiliza el registro estructurado manual.",
            "error_detallado": str(e),
            "categorias_disponibles": [{"id": c.id, "nombre": c.name} for c in categorias],
            "instruccion": "Envía los datos mediante el endpoint manual de creación de transacciones especificando el ID de categoría."
        }