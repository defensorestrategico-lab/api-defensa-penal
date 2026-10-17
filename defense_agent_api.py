"""Endpoint de auditoría estructurada. Sin publicación ni búsqueda jurídica simulada."""
import json,re,logging
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

DIAGNOSTIC_VERSION='R47-D1'
def fail(reason,status=502,upstream=0,finish=''):
 # Categorías controladas: nunca claves, prompts, documentos ni respuestas del modelo.
 allowed={'connection_timeout','connection_error','upstream_unavailable','upstream_rejected','response_envelope','missing_candidate','output_limit','generation_unfinished','empty_output','invalid_json','invalid_citation','invalid_contract','output_size'}
 if reason not in allowed:reason='invalid_contract'
 finish=finish if isinstance(finish,str) and finish in {'STOP','MAX_TOKENS','SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT','OTHER','MALFORMED_FUNCTION_CALL'} else 'UNKNOWN'
 logging.getLogger('uvicorn.error').warning('DEFENSOR_AGENT_DIAG version=%s reason=%s upstream_http=%s finish=%s',DIAGNOSTIC_VERSION,reason,upstream,finish)
 raise HTTPException(status,'Auditoría no completada. Diagnóstico: '+reason+'. Sin reintento automático.',headers={'X-Defensor-Diagnostic':reason})

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
  except requests.Timeout:fail('connection_timeout')
  except requests.RequestException:fail('connection_error')
  if r.status_code in (429,503):fail('upstream_unavailable',r.status_code,r.status_code)
  if r.status_code!=200:fail('upstream_rejected',502,r.status_code)
  try:envelope=r.json();c=envelope.get('candidates')
  except (ValueError,TypeError,AttributeError):fail('response_envelope',upstream=200)
  if not isinstance(c,list) or len(c)!=1 or not isinstance(c[0],dict):fail('missing_candidate',upstream=200)
  finish=c[0].get('finishReason')
  if finish=='MAX_TOKENS':fail('output_limit',upstream=200,finish=finish)
  if finish!='STOP':fail('generation_unfinished',upstream=200,finish=finish)
  try:text=''.join(x.get('text','') for x in c[0]['content']['parts'] if not x.get('thought'))
  except (ValueError,KeyError,TypeError,AttributeError):fail('response_envelope',upstream=200,finish=finish)
  if not text.strip():fail('empty_output',upstream=200,finish=finish)
  if len(text)>160000:fail('output_size',upstream=200,finish=finish)
  try:decoded=json.loads(text)
  except (ValueError,TypeError):fail('invalid_json',upstream=200,finish=finish)
  try:out=contract.validate(decoded,p)
  except (ValueError,KeyError,TypeError,AttributeError) as exc:
   citation=str(exc) in ('Cita ajena al material o inexistente.','Hallazgo o contrainterrogatorio sin soporte documental.','Criterio jurídico sin soporte en conocimiento seleccionado.','Dato del caso apoyado solo en conocimiento jurídico.')
   fail('invalid_citation' if citation else 'invalid_contract',upstream=200,finish=finish)
  return dict(out,model=model)
