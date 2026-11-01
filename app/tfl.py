"""Bounded TfL JourneyResults adapter. Fresh plans are never service guarantees."""
import re
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo
import httpx
from app.store import now

NOTICE='Freshly fetched planning estimate; recheck before travelling. Not a live departure prediction or accessibility guarantee.'

def london_time(value):
    if not value: return None
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=ZoneInfo('Europe/London'))
        return parsed.astimezone(ZoneInfo('Europe/London')).isoformat()
    except ValueError: return None

def postcode(value):
    compact=re.sub(r'\s+','',value).upper()
    if not re.fullmatch(r'(?:GIR0AA|[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2})',compact): raise ValueError('A complete UK postcode is required')
    return compact[:-3]+' '+compact[-3:]

def plan(origin,destination,appointment,avoid_stairs=False):
    origin=postcode(origin);destination=postcode(destination)
    date=datetime.fromisoformat(appointment)
    if date.tzinfo is None: raise ValueError('A timezone-aware arrival time is required')
    date=date.astimezone(ZoneInfo('Europe/London'))
    source='https://api.tfl.gov.uk/Journey/JourneyResults/'+quote(origin,safe='')+'/to/'+quote(destination,safe='')
    params={'date':date.strftime('%Y%m%d'),'time':date.strftime('%H%M'),'timeIs':'Arriving','journeyPreference':'LeastWalking','walkingSpeed':'Slow','useRealTimeLiveArrivals':'false','applyHtmlMarkup':'false'}
    if avoid_stairs: params['accessibilityPreference']=['NoSolidStairs']
    result={'mode':'unavailable','source':source,'checked_at':now(),'query':{'origin':origin,'destination':destination,**params},'journeys':[],'notice':NOTICE}
    try:
        response=httpx.get(source,params=params,timeout=12,follow_redirects=False)
        response.raise_for_status();payload=response.json()
        journeys=[]
        for item in payload.get('journeys',[])[:3]:
            legs=[{'mode':leg.get('mode',{}).get('id','unknown'),'instruction':str(leg.get('instruction',{}).get('summary','')).replace(chr(0x2014),'-'),
                   'departure':london_time(leg.get('departureTime')),'arrival':london_time(leg.get('arrivalTime')),'duration_minutes':leg.get('duration',0)} for leg in item.get('legs',[])[:20]]
            departure=london_time(item.get('startDateTime'));arrival=london_time(item.get('arrivalDateTime'))
            if not departure or not arrival or not datetime.fromisoformat(departure)<datetime.fromisoformat(arrival)<=date: continue
            journeys.append({'duration_minutes':item.get('duration'),'departure':departure,'arrival':arrival,
                             'walking_minutes':sum(leg['duration_minutes'] for leg in legs if leg['mode']=='walking'),'summary':' / '.join(leg['instruction'] for leg in legs),'legs':legs})
        result.update(mode='tfl-live-response' if journeys else 'unavailable',journeys=journeys)
        if journeys: result['selected_index']=min(range(len(journeys)),key=lambda index:(journeys[index]['walking_minutes'],journeys[index]['duration_minutes'] or 0))
        if not journeys: result['notice']='TfL returned no unambiguous journey options. Check the postcodes and date. '+NOTICE
    except Exception: result['notice']='TfL planning is unavailable. No route or departure time was invented. '+NOTICE
    return result
