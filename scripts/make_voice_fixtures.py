"""Generate synthetic computer-spoken recordings with macOS built-in speech."""
import json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'fixtures/voice'
for note in json.loads((root/'notes.json').read_text()):
    temp=root/(note['id']+'.aiff')
    subprocess.run(['say','-r','155','-o',str(temp),note['transcript']],check=True)
    subprocess.run(['afconvert','-f','WAVE','-d','LEI16@22050',str(temp),str(root/note['audio'])],check=True)
    temp.unlink()
print('Three synthetic speech fixtures generated using macOS say, not patient recordings.')
