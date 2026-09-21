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

@app.get("/transactions")
def listar_transacciones(
    skip: int = 0,
    limit: int = 100,
    type: str = None,
    category_id: int = None,
    db: Session = Depends(get_db)
):
    query = db.query(models.Transaction).filter(models.Transaction.user_id == 1)
    
    if type is not None:
        query = query.filter(models.Transaction.type == type)
        
    if category_id is not None:
        query = query.filter(models.Transaction.category_id == category_id)
        
    transactions = query.offset(skip).limit(limit).all()
    return transactions

@app.get("/transactions/summary")
def obtener_resumen_financiero(db: Session = Depends(get_db)):
    from sqlalchemy import func
    
    # Filtrar transacciones del usuario por defecto (user_id=1)
    transacciones_usuario = db.query(models.Transaction).filter(models.Transaction.user_id == 1).all()
    
    total_ingresos = sum(t.amount for t in transacciones_usuario if t.type == "ingreso")
    total_gastos = sum(t.amount for t in transacciones_usuario if t.type == "gasto")
    saldo_neto = total_ingresos - total_gastos
    
    # Desglose por categoría
    categorias = {c.id: c.name for c in db.query(models.Category).all()}
    desglose_categorias = {}
    
    for t in transacciones_usuario:
        cat_id = t.category_id
        cat_name = categorias.get(cat_id, "Desconocida")
        if cat_name not in desglose_categorias:
            desglose_categorias[cat_name] = {"category_id": cat_id, "ingresos": 0, "gastos": 0}
        
        if t.type == "ingreso":
            desglose_categorias[cat_name]["ingresos"] += float(t.amount)
        elif t.type == "gasto":
            desglose_categorias[cat_name]["gastos"] += float(t.amount)

    return {
        "user_id": 1,
        "total_ingresos": float(total_ingresos),
        "total_gastos": float(total_gastos),
        "saldo_neto": float(saldo_neto),
        "desglose_por_categoria": desglose_categorias
    }

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