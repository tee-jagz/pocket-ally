"""Generate editable synthetic messages from a bounded administrative context only."""
import json,os,re
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel,ConfigDict,Field
from app import cases,incoming
from app.store import now


class GenerationNotConfigured(Exception): pass
class GenerationUnavailable(Exception): pass


class GeneratedMessage(BaseModel):
    model_config=ConfigDict(extra='forbid')
    text:str=Field(min_length=30,max_length=3000,description='Realistic short incoming administrative message, visibly labelled SYNTHETIC DEMO. Preserve every supplied date/location exactly. No clinical or recipient details.')
    facts:incoming.Facts=Field(description='Extract these facts AFTER writing text. Every quote must be an exact verbatim substring of the generated text field, never a paraphrase or a phrase borrowed only from input context/request.')
    previous_appointment_quote:str|None=Field(description='For reschedule only, the exact source substring containing the supplied PREVIOUS full date, year and time. Otherwise null.')


def display_date(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/London')).strftime('%d %B %Y at %H:%M')


def known_label(value,expected):
    return isinstance(value,str) and value.strip().rstrip('.,;:')==expected


def known_hospital(value,hospital,department):
    return known_label(value,hospital) or known_label(value,hospital+' - '+department)


def weekly_context(store,visit_id):
    appointment=None;hospital=None;department=None
    if visit_id:
        try: selected=cases.get_case(store,'case-'+visit_id)
        except LookupError: raise ValueError('Choose an existing visit for this example')
        if selected.get('status')=='running' or selected.get('visit_assignment')=='unassigned':
            raise ValueError('Wait for the selected visit to finish preparing, or choose another visit')
        appointment=selected.get('appointment')
        fixture=cases.scenario('confirmed-visit')['event'];facts=selected.get('interpretation',{})
        labels=[facts]+selected['events']
        if any(known_hospital(row.get('hospital'),fixture['hospital'],fixture['department']) for row in labels):
            hospital=fixture['hospital']
            if any(known_label(row.get('department'),fixture['department']) for row in labels): department=fixture['department']
    return {'scenario_id':'checkup-email','intent':'checkup','appointment':appointment,'appointment_text':display_date(appointment) if appointment else None,
            'previous_appointment':None,'previous_appointment_text':None,'hospital':hospital,'department':department,'receipt_available':False,
            'request':'How have you been this past week? Have you noticed any changes in how you are feeling or managing day to day?'}


def admin_context(store,scenario_id,visit_id=None):
    scenario=cases.scenario(scenario_id)
    if scenario_id=='checkup-email': return weekly_context(store,visit_id)
    fixture=cases.scenario('attended-visit' if scenario_id=='attended-visit' else 'confirmed-visit')['event']
    current=datetime.fromisoformat(now())
    hospital=fixture['hospital'];department=fixture['department'];appointment=fixture['appointment']
    selected=None;using_fixture=not visit_id
    if visit_id:
        try: selected=cases.get_case(store,'case-'+visit_id)
        except LookupError: raise ValueError('Choose an existing confirmed visit for this example')
        if selected.get('status')=='running' or selected.get('visit_assignment')=='unassigned':
            raise ValueError('Wait for the selected visit to finish preparing, or choose an existing confirmed visit')
        facts=selected.get('interpretation',{})
        sourced=[event for event in selected['events'] if known_hospital(event.get('hospital'),hospital,department) and known_label(event.get('department'),department)]
        verified_location=bool(sourced or known_hospital(facts.get('hospital'),hospital,department))
        if not sourced and not known_label(facts.get('department'),department): department=None
        appointment=selected.get('appointment') or (facts.get('appointment') if facts.get('intent')=='attendance' else None)
        checkup_only=not appointment and (facts.get('intent')=='checkup' or any(event.get('type')=='checkup-email' for event in selected['events']))
        if checkup_only and scenario_id=='confirmed-visit':
            # This is a new fictional incoming confirmation, not a claim that the
            # earlier check-in already confirmed a date or a hospital.
            appointment=fixture['appointment'];department=fixture['department']
            verified_location=True;using_fixture=True
        if scenario_id=='attended-visit':
            past=next((event for event in reversed(sourced) if event.get('attended')),None)
            if past: appointment=past['appointment']
            if not appointment or appointment!=fixture['appointment'] or not (past or facts.get('intent')=='attendance'):
                raise ValueError('Choose the known past synthetic attendance visit; a future visit cannot become attendance')
        elif not appointment or datetime.fromisoformat(appointment)<=current:
            raise ValueError('Choose an existing confirmed future visit for this example')
        if not verified_location: raise ValueError('The selected visit needs a verified synthetic hospital before generating this example')
        if scenario_id=='attended-visit' and not department: raise ValueError('The past synthetic attendance needs its verified department')
    if scenario_id=='reschedule' and not selected: raise ValueError('Select an existing confirmed visit before generating a reschedule')
    intent={'checkup-email':'checkup','confirmed-visit':'appointment','attended-visit':'attendance','reschedule':'reschedule'}[scenario_id]
    previous=None
    if intent=='reschedule':
        previous=appointment
        appointment=(datetime.fromisoformat(appointment)+timedelta(days=2)).isoformat()
    elif intent!='attendance' and using_fixture and datetime.fromisoformat(appointment)<=current:
        appointment=(current.astimezone(ZoneInfo('Europe/London'))+timedelta(days=10)).replace(hour=14,minute=0,second=0,microsecond=0).isoformat()
    receipt=bool(selected and any(event.get('receipt_fixture_verified') for event in selected['events']))
    request={
        'appointment':'Your appointment is confirmed for the date and location shown. Please allow enough time for your journey and bring your appointment details.',
        'reschedule':'This replaces your previous appointment booking. Please allow enough time for your journey to the revised appointment.',
        'attendance':'This confirms that you attended the appointment stated above. '+('The synthetic travel receipt has been provided.' if receipt else 'Your travel receipt is still missing.')
    }[intent]
    return {'scenario_id':scenario['id'],'intent':intent,'appointment':appointment,'appointment_text':display_date(appointment),
            'previous_appointment':previous,'previous_appointment_text':display_date(previous) if previous else None,
            'hospital':hospital,'department':department,'receipt_available':receipt,'request':request}


def validate_message(generated,context):
    text=generated.text.strip()
    if chr(0x2014) in text or 'SYNTHETIC' not in text.upper(): raise ValueError('Synthetic label required')
    checked=incoming.validate_facts({'text':text,'timestamp':now()},generated.facts,'responses')
    weekly=context['intent']=='checkup'
    if checked['intent']!=context['intent'] or (checked['appointment']!=context['appointment'] and (not weekly or checked['appointment'] is not None)):
        raise ValueError('Generated date or intent differs from the supplied facts')
    if any(checked[key]!=context[key] and (not weekly or checked[key] is not None) for key in ('hospital','department')):
        raise ValueError('Generated location differs from verified synthetic context')
    if checked['missing_info'] and any(item['id']!='visit-target' for item in checked['missing_info']):
        raise ValueError('Generated facts are incomplete')
    if checked['appointment'] is not None and context['appointment_text'] not in text: raise ValueError('Exact current date required')
    if context['previous_appointment']:
        old=generated.previous_appointment_quote
        if not old or old not in text or incoming.parsed_date(old)!=context['previous_appointment']:
            raise ValueError('Exact previous appointment required')
    elif generated.previous_appointment_quote is not None: raise ValueError('Unexpected previous appointment')
    spans=re.findall(r'\b\d{1,2}\s+[A-Za-z]+\s+20\d{2}\s+(?:at\s+)?\d{1,2}:\d{2}|\b20\d{2}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?',text,re.I)
    if any(incoming.parsed_date(span) is None or incoming.parsed_date(span) not in (context['appointment'],context['previous_appointment']) for span in spans):
        raise ValueError('Unexpected appointment date')
    rest=text.replace(context['hospital'] or '','').replace(context['department'] or '','')
    if re.search(r'@|https?://|\b(?:hospital|clinic|hospice|cancer centre)\b',rest,re.I): raise ValueError('Unexpected recipient or location')
    if re.search(r'\b(?:diagnos\w*|treatment|medication|prognosis)\b|\b(?:refund|eligibility)\s+(?:is\s+)?(?:confirmed|guaranteed)|\byou\s+(?:are eligible|qualify)\b',text,re.I):
        raise ValueError('Unsupported clinical or financial statement')
    if generated.facts.receipt_available!=context['receipt_available']: raise ValueError('Receipt availability changed')
    if re.search(r'\blocal calendar\b|\bsame existing visit\b|\bcreat(?:e|ing) another visit\b|\b(?:prepare|generate|register|update)\b.{0,35}\b(?:paperwork|summary|calendar|draft|case|visit|tool)\b',text,re.I):
        raise ValueError('An incoming example must not contain app or builder instructions')
    if context['intent']=='attendance' and not context['receipt_available'] and not re.search(r'\b(?:missing|unavailable|not yet|no receipt)\b',text,re.I):
        raise ValueError('Missing receipt must stay explicit')
    return text


async def generate(store,scenario_id,visit_id=None):
    context=admin_context(store,scenario_id,visit_id)
    if not os.getenv('OPENAI_API_KEY'): raise GenerationNotConfigured('Example generation is unavailable because the OpenAI text service is not configured')
    try:
        from openai import AsyncOpenAI
        async with AsyncOpenAI(timeout=40,max_retries=0) as client:
            response=await client.responses.parse(model=os.getenv('OPENAI_EXAMPLE_MODEL','gpt-6-luna'),reasoning={'effort':'none'},store=False,text_format=GeneratedMessage,max_output_tokens=1200,
                instructions='Write a brief, realistic SYNTHETIC DEMO email from an appointments administrator to a patient, using ONLY the supplied synthetic administrative facts. Return natural email text and exact supporting fact quotes. Follow intent exactly: appointment confirms a future booking; attendance confirms the recipient already attended; checkup is a natural question from a doctor: how have you been this past week, and have you noticed changes in how you feel or manage day to day. Do not prescribe walking/stairs topics or call the email a check-in summary; reschedule says the new date replaces the previous booking. Use appointment_text and previous_appointment_text verbatim. For checkup, appointment background is optional and must not lead the email: omit unknown dates/locations, and set their fact fields null unless actually written. For all other intents populate facts.appointment and its exact source quote with the current/new date; never use the previous date there. For reschedule include the previous complete date/time and its exact quote separately. For noncheckup intents include the exact supplied Location and optional Department; omit unknown values and return null. Preserve receipt_available and explicitly mention a missing travel receipt for attendance when false. Use request as natural email content. Do not invent observations, dates, facilities, recipients, addresses, URLs, clinical details or financial promises. Make no delivery, sharing, payment or external-booking claims. Do not instruct an app or mention local calendars, tools, drafts, SAME existing visit or creating another visit. This only fills an editable example. CRITICAL: Write the email first, then extract facts from that generated text, not from the input JSON. facts.intent_quote must be a SHORT VERBATIM substring that actually appears in your text: for example you attended, has been rescheduled, appointment is confirmed, or bring a short account, only if those exact words appear. Never copy context.request as a quote unless you copied it unchanged into your email. All quoted fields must match your generated text exactly, with no paraphrasing. No em dash. Keep the email under 130 words.',
                input=json.dumps(context))
        if response.output_parsed is None: raise ValueError('No structured example returned')
        text=validate_message(response.output_parsed,context)
    except Exception:
        raise GenerationUnavailable('The example could not be generated with the verified synthetic facts. Try again or write your own message.') from None
    summary='Synthetic weekly question. No journal text is used to generate it.' if context['intent']=='checkup' else 'Synthetic administrative context: '+context['appointment_text']+' at '+context['hospital']+'. No delivery is started by generation.'
    result={'text':text,'generation_mode':'responses','context_summary':summary}
    if visit_id: result['visit_id']=visit_id
    if context['intent'] in ('appointment','reschedule'): result.update(origin='E15 1AA',destination='WC1E 6AG')
    return result
