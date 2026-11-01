"""Run only with server stopped. Archive run state; preserve OAuth credentials."""
from datetime import datetime,timezone
from pathlib import Path
import shutil
root=Path(__file__).resolve().parents[1]/'data'
archive=root/'archives'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
for name in ('state.sqlite3','state.sqlite3-wal','state.sqlite3-shm','next-appointment.ics','hc5-draft.pdf','outbox'):
    p=root/name
    if p.exists():
        archive.mkdir(parents=True,exist_ok=True); shutil.move(str(p),str(archive/name))
print('Synthetic demo state archived under ignored data/archives. OAuth files preserved.')
