import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def parse_transaction_with_ai(text: str):
    completion = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente financiero experto. Extrae la información de la transacción "
                    "y respóndela estrictamente en formato JSON con estas claves exactas:\n"
                    '- "type": obligatorio, SOLO "gasto" o "ingreso" (en español, minúsculas)\n'
                    '- "amount": obligatorio, número positivo sin símbolos ni separadores\n'
                    '- "currency": siempre "CLP"\n'
                    '- "merchant": string o null (local o comercio mencionado)\n'
                    '- "category_id": entero o null (usa estos IDs si reconoces la categoría: '
                    '1=Alimentación, 2=Transporte, 3=Ocio y Entretenimiento, 4=Hogar, 5=Feria, '
                    '6=Salud, 7=Sin Categorizar, 8=Servicios, 9=Vestuario, 10=Educación, '
                    '11=Inversiones, 12=Sueldo y Salario, 13=Freelance, 14=Regalos, '
                    '15=Viajes, 16=Mascotas, 17=Deporte)\n'
                    '- "description": string corto y descriptivo en español\n'
                    "No incluyas ningún texto fuera del JSON."
                )
            },
            {
                "role": "user",
                "content": text
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    return completion.choices[0].message.content