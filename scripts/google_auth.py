"""User-run only: OAuth for a throwaway Google account."""
import os
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
load_dotenv()
SCOPES=['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.send','https://www.googleapis.com/auth/calendar.events','https://www.googleapis.com/auth/calendar.calendarlist.readonly']
if __name__=='__main__':
    flow=InstalledAppFlow.from_client_secrets_file(os.getenv('GOOGLE_CLIENT_FILE','data/google-client.json'),SCOPES)
    creds=flow.run_local_server(port=0)
    path=Path(os.getenv('GOOGLE_TOKEN_FILE','data/google-token.json')); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(creds.to_json()); path.chmod(0o600)
    print('OAuth token saved to the ignored data directory. No token printed.')
