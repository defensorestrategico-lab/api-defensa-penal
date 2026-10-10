import os
import re
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

app = FastAPI(
    title="API Defensores Estratégico Penal",
    description="Servicio backend para consulta procesal y análisis penal estratégico con IA.",
    version="1.0.0"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

class ConsultaRamaRequest(BaseModel):
    numero_radicado: str = Field(
        ..., 
        min_length=21, 
        max_length=21, 
        description="Número de radicado único del proceso (21 dígitos)"
    )

class ActuacionProcesal(BaseModel):
    fecha: str
    actuacion: str
    anotacion: Optional[str] = None
    despacho: Optional[str] = None

class ConsultaRamaResponse(BaseModel):
    numero_radicado: str
    sujetos_procesales: List[str]
    actuaciones: List[ActuacionProcesal]
    fuente: str

class AnalisisActuacionRequest(BaseModel):
    numero_radicado: Optional[str] = None
    delito: Optional[str] = "No especificado"
    etapa_procesal: Optional[str] = "Indagación / Investigación"
    texto_actuacion: str = Field(..., description="Texto de la actuación o providencia a analizar")

class AnalisisActuacionResponse(BaseModel):
    resumen_ejecutivo: str
    riesgos_defensivos: List[str]
    oportunidades_probatorias: List[str]
    estrategia_sugerida: str

@app.get("/", tags=["Estado"])
def read_root():
    return {
        "sistema": "Defensores Estratégico Penal API",
        "estado": "Operativo",
        "version": "1.0.0"
    }

@app.post("/consultar-rama", response_model=ConsultaRamaResponse, tags=["Consulta Judicial"])
def consultar_rama(payload: ConsultaRamaRequest):
    radicado = payload.numero_radicado
    if not re.match(r"^\d{21}$", radicado):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El código de radicado debe contener exactamente 21 dígitos numéricos."
        )
    
    url_consulta = f"https://consultaprocesos.ramajudicial.gov.co:443/api/v1/Proceso/Consulta/NumeroRadicacion?numero={radicado}&IsConsultarActuaciones=true"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url_consulta, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            procesos = data.get("procesos", [])
            if not procesos:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No se encontraron registros para el número de radicado provisto."
                )
            
            proceso_principal = procesos[0]
            id_proceso = proceso_principal.get("idProceso")
            
            url_actuaciones = f"https://consultaprocesos.ramajudicial.gov.co:443/api/v1/Proceso/Consulta/Actuaciones/{id_proceso}"
            res_act = requests.get(url_actuaciones, headers=headers, timeout=15)
            
            actuaciones_list = []
            if res_act.status_code == 200:
                act_data = res_act.json().get("actuaciones", [])
                for item in act_data:
                    actuaciones_list.append(ActuacionProcesal(
                        fecha=item.get("fechaActuacion", ""),
                        actuacion=item.get("actuacion", ""),
                        anotacion=item.get("anotacion", ""),
                        despacho=item.get("despacho", "")
                    ))
            
            sujetos = [proceso_principal.get("sujetosProcesales", "No especificado")]
            return ConsultaRamaResponse(
                numero_radicado=radicado,
                sujetos_procesales=sujetos,
                actuaciones=actuaciones_list,
                fuente="Rama Judicial / SPOA - TYBA"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error al conectar con la Rama Judicial. Código: {response.status_code}"
            )
    except requests.RequestException as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Fallo de conexión externa: {str(e)}"
        )

@app.post("/analizar-actuacion", response_model=AnalisisActuacionResponse, tags=["Inteligencia Artificial"])
def analizar_actuacion(payload: AnalisisActuacionRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="La variable de entorno GEMINI_API_KEY no está configurada en el servidor."
        )
    
    prompt = f"""
    Eres un abogado penalista experto en el sistema penal acusatorio colombiano (Ley 906 de 2004).
    Analiza la siguiente actuación procesal y proporciona una evaluación defensiva estructurada.
    CONTEXTO:
    - Número de Radicado: {payload.numero_radicado or 'No aportado'}
    - Delito Imputado/Investigado: {payload.delito}
    - Etapa Procesal: {payload.etapa_procesal}
    TEXTO DE LA ACTUACIÓN / PROVIDENCIA:
    \"\"\"{payload.texto_actuacion}\"\"\"
    RESPONDE EXACTAMENTE EN EL SIGUIENTE FORMATO SEPARADO POR SECCIONES:
    [RESUMEN]
    Un resumen ejecutivo claro de un párrafo.
    [RIESGOS]
    - Riesgo 1
    - Riesgo 2
    [OPORTUNIDADES]
    - Oportunidad o prueba 1
    - Oportunidad o prueba 2
    [ESTRATEGIA]
    Recomendación estratégica para la defensa técnica.
    """
    
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        texto_generado = response.text
        
        resumen = "Análisis completado exitosamente."
        riesgos = []
        oportunidades = []
        estrategia = "Revisar los términos procesales vigentes."
        
        if "[RESUMEN]" in texto_generado and "[RIESGOS]" in texto_generado:
            resumen = texto_generado.split("[RESUMEN]")[1].split("[RIESGOS]")[0].strip()
        
        if "[RIESGOS]" in texto_generado and "[OPORTUNIDADES]" in texto_generado:
            bloque_riesgos = texto_generado.split("[RIESGOS]")[1].split("[OPORTUNIDADES]")[0].strip()
            riesgos = [r.replace("-", "").strip() for r in bloque_riesgos.split("\n") if r.strip()]
        
        if "[OPORTUNIDADES]" in texto_generado and "[ESTRATEGIA]" in texto_generado:
            bloque_op = texto_generado.split("[OPORTUNIDADES]")[1].split("[ESTRATEGIA]")[0].strip()
            oportunidades = [o.replace("-", "").strip() for o in bloque_op.split("\n") if o.strip()]
        
        if "[ESTRATEGIA]" in texto_generado:
            estrategia = texto_generado.split("[ESTRATEGIA]")[1].strip()
        
        return AnalisisActuacionResponse(
            resumen_ejecutivo=resumen,
            riesgos_defensivos=riesgos if riesgos else ["Revisión de garantías constitucionales."],
            oportunidades_probatorias=oportunidades if oportunidades else ["Solicitud de elementos material probatorio."],
            estrategia_sugerida=estrategia
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error durante el procesamiento del motor IA: {str(e)}"
        )
