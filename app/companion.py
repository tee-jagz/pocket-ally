"""Safe, explicit companion preview and selection; no generated executable markup."""
import hashlib,os,secrets
from app.store import LOCK,now

STYLES=('soft','playful','minimal')

def state(store):
    return {'saved':store.get('companion_saved'),'previews':store.get('companion_previews',[]),'styles':list(STYLES)}

def preview(store,prompt,style):
    seed=hashlib.sha256((style+'\n'+prompt).encode()).digest()
    id=secrets.token_hex(12)
    result={'id':id,'prompt':prompt,'style':style,'mode':'local-personalised-preview',
            'image_url':'/assets/companion-'+style+'.png',
            'descriptor':{'hue':int.from_bytes(seed[:2],'big')%360,
                          'accent_hue':int.from_bytes(seed[2:4],'big')%360,
                          'shape':('round','squircle','oval')[seed[4]%3]},'created_at':now()}
    if os.getenv('OPENAI_API_KEY'):
        from app.integrations import generate_companion_image
        try: content=generate_companion_image(prompt,style)
        except Exception:
            result['fallback_reason']='Image service unavailable. Showing a personalised style preview.'
        else:
            directory=store.root/'companions';directory.mkdir(exist_ok=True)
            path=directory/(id+'.png');path.write_bytes(content);path.chmod(0o600)
            result.update(mode='openai-generated',image_url='/api/companion/images/'+id)
    with LOCK:
        previews=store.get('companion_previews',[])
        store.put('companion_previews',[result]+previews[:19])
    return result

def select(store,id):
    with LOCK:
        selected=next((item for item in store.get('companion_previews',[]) if item['id']==id),None)
        if not selected: raise LookupError('Companion preview not found')
        store.put('companion_saved',selected)
    return selected
