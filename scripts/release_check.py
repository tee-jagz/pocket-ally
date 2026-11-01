"""Scan candidate source files without printing secret values."""
import re,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
blocked=[]
for p in root.rglob('*'):
    if not p.is_file(): continue
    rel=p.relative_to(root)
    if any(s in rel.parts for s in ('.git','.venv','__pycache__','.pytest_cache')) or rel.parts[0]=='data': continue
    if p.name.startswith('.env') and p.name!='.env.example': continue
    if p.suffix in ('.pdf','.wav','.webm','.png','.jpg'): continue
    text=p.read_text(errors='ignore')
    if re.search(r'\bsk-[A-Za-z0-9_-]{20,}',text) or ('-----BEGIN '+'PRIVATE KEY-----') in text:
        blocked.append(str(rel))
print('Secret-pattern scan: '+('FAIL in '+', '.join(blocked) if blocked else 'PASS (heuristic; inspect staged files too)'))
try:
    tracked=subprocess.check_output(['git','ls-files'],cwd=root,text=True,stderr=subprocess.DEVNULL).splitlines()
    unsafe=[p for p in tracked if (p.startswith('data/') and p!='data/.gitkeep') or p=='.env' or 'token.json' in p or 'credentials' in p]
    if unsafe: blocked+=unsafe;print('Unsafe tracked paths: '+', '.join(unsafe))
except subprocess.CalledProcessError: print('Git not initialized; public repository not verified.')
sys.exit(bool(blocked))
