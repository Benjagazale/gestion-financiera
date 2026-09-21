import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
URL_API = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={GEMINI_API_KEY}"

def procesar_mensaje_con_gemini(mensaje_usuario: str, max_intentos: int = 3):
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": f"Analiza el siguiente mensaje y extrae la información solicitada: \"{mensaje_usuario}\""}]}],
        "systemInstruction": {
            "parts": [{"text": "Eres un asistente financiero. Devuelve estrictamente un JSON con: type (gasto/ingreso), amount (número), currency (CLP), merchant (opcional), category_id (1 a 7) y description (opcional)."}]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.1
        }
    }

    ultimo_error = None
    for intento in range(1, max_intentos + 1):
        try:
            response = requests.post(URL_API, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                ultimo_error = f"Error HTTP {response.status_code}: {response.text}"
        except Exception as e:
            ultimo_error = str(e)
        
        # Si falla, espera antes del siguiente intento (2s, luego 4s)
        if intento < max_intentos:
            time.sleep(intento * 2)

    raise Exception(f"Fallo tras {max_intentos} intentos. Último error: {ultimo_error}")