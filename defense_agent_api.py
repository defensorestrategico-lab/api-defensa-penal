"""Endpoint de auditoría estructurada. Sin publicación ni búsqueda jurídica simulada."""
import json,re
import requests
from fastapi import Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
import defense_agent_contract as contract
class AgentRequest(BaseModel):
 model_config=ConfigDict(extra='forbid')
 packet:dict
 model:str=Field(min_length=1,max_length=100)
 confirmed_external:bool
 confirmed_fictitious:bool

def install(app,access,configuration,reserve,convert_schema):
 @app.post('/auditar-defensa',tags=['Agente de defensa'])
 def audit(payload:AgentRequest,authorized=Depends(access)):
  key,model=configuration()
  if not payload.confirmed_external or not payload.confirmed_fictitious:raise HTTPException(422,'Piloto: confirma material ficticio y envío externo.')
  if payload.model!=model:raise HTTPException(409,'Modelo remoto diferente de la sesión local.')
  try:
   p=contract.prepare(payload.packet['context'],payload.packet['sources'],payload.packet['coverage'])
   if p!=payload.packet:raise ValueError()
  except (ValueError,KeyError,TypeError):raise HTTPException(422,'Material o cobertura inválidos; no se envió al proveedor.')
  if not key or not re.fullmatch(r'gemini-[a-zA-Z0-9.\-]+',model):raise HTTPException(503,'Configuración Gemini incompleta.')
  reserve()
  try:
   r=requests.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',headers={'x-goog-api-key':key},json={'systemInstruction':{'parts':[{'text':contract.PROMPT}]},'contents':[{'role':'user','parts':[{'text':json.dumps(p,ensure_ascii=False)}]}],'generationConfig':{'responseMimeType':'application/json','responseSchema':convert_schema(contract.schema()),'temperature':0.2,'maxOutputTokens':5000}},timeout=(10,55),allow_redirects=False)
  except requests.RequestException:raise HTTPException(502,'No se completó conexión al proveedor; sin reintento automático.')
  if r.status_code in (429,503):raise HTTPException(r.status_code,'Proveedor sin disponibilidad o cuota; sin reintento automático.')
  if r.status_code!=200:raise HTTPException(502,'Proveedor rechazó la auditoría; sin reintento automático.')
  try:
   c=r.json()['candidates']
   if len(c)!=1 or c[0].get('finishReason')!='STOP':raise ValueError()
   text=''.join(x.get('text','') for x in c[0]['content']['parts'] if not x.get('thought'))
   if len(text)>160000:raise ValueError()
   out=contract.validate(json.loads(text),p)
  except (ValueError,KeyError,TypeError,AttributeError):raise HTTPException(502,'Respuesta incompleta o soporte inválido; no se sustituyó por análisis ficticio.')
  return dict(out,model=model)
