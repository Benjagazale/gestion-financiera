from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import get_db
import models
from gemini_service import parse_transaction_with_ai
import json

app = FastAPI(title="Agente Financiero API", version="1.0")

@app.get("/health")
def health_check():
    return {"status": "ok"}

class TransactionParseRequest(BaseModel):
    text: str

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
    query = db.query(models.Transaction).filter(models.Transaction.user_id == "1")
    
    if type is not None:
        query = query.filter(models.Transaction.type == type)
        
    if category_id is not None:
        query = query.filter(models.Transaction.category_id == category_id)
        
    transactions = query.offset(skip).limit(limit).all()
    return transactions

@app.get("/transactions/summary")
def obtener_resumen_financiero(db: Session = Depends(get_db)):
    from decimal import Decimal
    
    # Filtrar transacciones del usuario por defecto (user_id="1")
    transacciones_usuario = db.query(models.Transaction).filter(models.Transaction.user_id == "1").all()
    
    total_ingresos = sum([t.amount for t in transacciones_usuario if t.type == "ingreso"], Decimal('0'))
    total_gastos = sum([t.amount for t in transacciones_usuario if t.type == "gasto"], Decimal('0'))
    saldo_neto = total_ingresos - total_gastos
    
    # Desglose por categoría
    categorias = {c.id: c.name for c in db.query(models.Category).all()}
    desglose_categorias = {}
    
    for t in transacciones_usuario:
        cat_id = t.category_id
        cat_name = categorias.get(cat_id, "Desconocida")
        if cat_name not in desglose_categorias:
            desglose_categorias[cat_name] = {"category_id": cat_id, "ingresos": 0.0, "gastos": 0.0}
        
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
        # Intentamos procesar con la IA
        resultado_json_str = parse_transaction_with_ai(mensaje)
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

@app.post("/transactions/parse")
def parsear_transaccion(payload: TransactionParseRequest, db: Session = Depends(get_db)):
    """
    Procesa una frase en lenguaje natural con la IA (Groq/llama), extrae los datos
    de la transacción (monto, tipo, descripción y categoría) y la guarda en
    Supabase para el usuario por defecto (user_id="1").
    """
    # 1. Consultar categorías para poder resolver nombres de categoría a IDs
    categorias = db.query(models.Category).filter(models.Category.is_active == True).all()
    categorias_por_nombre = {c.name.strip().lower(): c.id for c in categorias}

    # 2. Pedir a la IA que extraiga la información estructurada
    try:
        resultado_json_str = parse_transaction_with_ai(payload.text)
        datos = json.loads(resultado_json_str)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo procesar el texto con la IA: {str(e)}"
        )

    # 3. Validar y normalizar los datos extraídos
    monto = datos.get("amount")
    tipo = str(datos.get("type", "")).strip().lower()

    if monto is None:
        raise HTTPException(status_code=422, detail="La IA no pudo extraer un monto válido del texto.")
    if tipo not in ("gasto", "ingreso"):
        raise HTTPException(status_code=422, detail=f"Tipo inválido extraído por la IA: '{tipo}'. Debe ser 'gasto' o 'ingreso'.")

    # 4. Resolver la categoría: la IA puede devolver category_id (int) o category (str)
    category_id = datos.get("category_id")
    category_nombre = datos.get("category")

    if category_id is None and category_nombre:
        category_id = categorias_por_nombre.get(str(category_nombre).strip().lower())

    if category_id is None:
        category_id = 7  # "Sin Categorizar" / valor por defecto del modelo

    # 5. Guardar la transacción en Supabase
    nueva_transaccion = models.Transaction(
        user_id="1",  # Usuario por defecto
        type=tipo,
        amount=float(monto),
        currency=datos.get("currency", "CLP"),
        merchant=datos.get("merchant"),
        category_id=int(category_id),
        description=datos.get("description") or payload.text
    )

    try:
        db.add(nueva_transaccion)
        db.commit()
        db.refresh(nueva_transaccion)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al guardar la transacción: {str(e)}")

    return {
        "status": "success",
        "message": "Transacción extraída por IA y guardada con éxito en la base de datos.",
        "extracted_data": {
            "amount": float(monto),
            "type": tipo,
            "description": datos.get("description") or payload.text,
            "category_id": int(category_id),
            "category_name": next((c.name for c in categorias if c.id == int(category_id)), None),
            "currency": datos.get("currency", "CLP"),
            "merchant": datos.get("merchant")
        },
        "transaction": nueva_transaccion
    }