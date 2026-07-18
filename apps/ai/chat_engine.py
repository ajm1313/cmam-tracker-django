"""
Clinical Assistant Chat Engine

Provides CMAM-specific clinical guidance using an LLM API (OpenAI-compatible).
Falls back to a rule-based response system when no API key is configured,
ensuring the assistant is always functional even without external API access.

The system prompt embeds CMAM protocols (WHO/Nigeria guidelines) so responses
are grounded in clinical best practices for malnutrition management.
"""
import logging
import json

logger = logging.getLogger(__name__)

CMAM_SYSTEM_PROMPT = """You are a CMAM (Community-based Management of Acute Malnutrition) clinical assistant integrated into the CMAM Tracker application.

Your role is to help healthcare workers manage cases of Severe Acute Malnutrition (SAM) and Moderate Acute Malnutrition (MAM) in children.

Key CMAM Protocols (WHO/Nigeria guidelines):
- SAM: MUAC < 11.5cm, WFH/WFL < -3SD, or bilateral pitting oedema
- MAM: MUAC 11.5-12.4cm, WFH/WFL < -2SD
- High-risk MAM: MUAC 11.5-12.4cm with medical complications or < 6 months with growth faltering
- RUTF dosage: 130-200 kcal/kg/day for SAM, adjusted by weight
- SAM follow-up: Weekly visits until discharge (typically 6-8 weeks)
- MAM follow-up: Biweekly visits until discharge (typically 8-12 weeks)
- Discharge criteria (SAM): MUAC >= 12.5cm for 2 consecutive visits, no oedema, weight gain
- Discharge criteria (MAM): MUAC >= 12.5cm for 2 consecutive visits
- Default: 3 consecutive missed visits
- IPC referral: Failed appetite test, severe medical complications, or worsening condition
- Medicines at enrollment: Amoxicillin (SAM), Vitamin A, Folic acid, Deworming (week 2), Measles vaccine (week 4)

Guidelines for responses:
1. Always reference specific CMAM protocols when giving clinical advice
2. Ask for relevant patient details (age, MUAC, weight, oedema status) when needed
3. Recommend IPC referral when appetite test fails or severe complications present
4. Emphasize the importance of routine follow-up visits
5. Never override a clinician's judgment - provide supportive guidance only
6. If asked about non-CMAM topics, gently redirect to malnutrition management
7. Keep responses concise and actionable for field workers

Remember: You are a decision-support tool, not a replacement for clinical judgment."""

# Rule-based fallback knowledge base
FALLBACK_KNOWLEDGE = {
    'sam': {
        'keywords': ['sam', 'severe', 'acute malnutrition', 'muac', '11.5'],
        'response': (
            'SAM (Severe Acute Malnutrition) is identified by:\n'
            '- MUAC < 11.5 cm (6-59 months)\n'
            '- WFH/WFL Z-score < -3SD\n'
            '- Bilateral pitting oedema (Grade +, ++, ++++)\n\n'
            'Management:\n'
            '- RUTF at 130-200 kcal/kg/day\n'
            '- Weekly follow-up visits\n'
            '- Amoxicillin at enrollment (if no complications)\n'
            '- Vitamin A, Folic acid on Day 1\n'
            '- Deworming at Week 2\n'
            '- Measles vaccine at Week 4\n'
            '- Discharge: MUAC >= 12.5cm for 2 visits, no oedema, weight gain\n'
            '- IPC referral if appetite test fails or severe complications'
        )
    },
    'mam': {
        'keywords': ['mam', 'moderate', '12.4', '12.0'],
        'response': (
            'MAM (Moderate Acute Malnutrition) is identified by:\n'
            '- MUAC 11.5-12.4 cm (6-59 months)\n'
            '- WFH/WFL Z-score < -2SD\n\n'
            'Management:\n'
            '- High-risk MAM: Treated like SAM (weekly visits, RUTF)\n'
            '- Other MAM: Biweekly visits, supplementary food (RUSF/CSB+)\n'
            '- Discharge: MUAC >= 12.5cm for 2 consecutive visits\n'
            '- Refer to SAM if condition worsens'
        )
    },
    'rutf': {
        'keywords': ['rutf', 'dosage', 'ration', 'sachet'],
        'response': (
            'RUTF (Ready-to-Use Therapeutic Food) Dosage:\n'
            '- SAM: 130-200 kcal/kg/day\n'
            '- Typical: 2-3 sachets/day for 5-7kg child, 3-4 for 7-10kg\n'
            '- High-risk MAM: Same as SAM\n'
            '- Other MAM: Supplementary feeding (RUSF or CSB+)\n\n'
            'Appetite test: Give RUTF at clinic, observe if child eats willingly.\n'
            'Failed appetite test = IPC referral required.'
        )
    },
    'default': {
        'keywords': ['default', 'missed', 'absent', 'lost to follow'],
        'response': (
            'Defaulting in CMAM:\n'
            '- Defined as 3 consecutive missed/absent visits\n'
            '- After 1 missed visit: Call caregiver, remind next appointment\n'
            '- After 2 missed visits: Schedule home visit\n'
            '- After 3 missed visits: Mark as defaulted, active tracing\n'
            '- Use community volunteers for tracing\n'
            '- Readmission possible if child returns and still meets criteria'
        )
    },
    'oedema': {
        'keywords': ['oedema', 'edema', 'swelling'],
        'response': (
            'Oedema in CMAM:\n'
            '- Grade +: Mild, both feet\n'
            '- Grade ++: Moderate, feet + lower legs\n'
            '- Grade +++: Severe, feet + legs + face\n\n'
            '- Any bilateral pitting oedema = SAM regardless of MUAC\n'
            '- Grade ++/+++ requires IPC admission\n'
            '- Monitor oedema reduction at each visit\n'
            '- Discharge requires no oedema for 2 consecutive visits'
        )
    },
    'discharge': {
        'keywords': ['discharge', 'cured', 'recovered', 'exit'],
        'response': (
            'Discharge Criteria (CMAM):\n'
            'SAM Cured:\n'
            '- MUAC >= 12.5 cm for 2 consecutive visits\n'
            '- No oedema for 2 consecutive visits\n'
            '- Weight gain confirmed\n'
            '- Minimum 3 weeks in treatment\n\n'
            'MAM Cured:\n'
            '- MUAC >= 12.5 cm for 2 consecutive visits\n\n'
            'Other exits: Death, Default (3 absences), Transfer, Non-response'
        )
    },
    'ipc': {
        'keywords': ['ipc', 'inpatient', 'referral', 'admit'],
        'response': (
            'IPC (Inpatient Therapeutic Care) Referral:\n'
            'Refer to IPC when:\n'
            '- Appetite test fails (child refuses RUTF)\n'
            '- Severe medical complications (severe pneumonia, sepsis, severe dehydration)\n'
            '- Grade ++/+++ oedema\n'
            '- Weight loss despite treatment\n'
            '- Severe anaemia, hypothermia, or lethargy\n\n'
            'Transfer with referral form and treatment summary.'
        )
    },
    'visit': {
        'keywords': ['visit', 'follow', 'schedule', 'when', 'next'],
        'response': (
            'Visit Schedule:\n'
            '- SAM: Weekly visits (every 7 days)\n'
            '- MAM: Biweekly visits (every 14 days)\n'
            '- High-risk MAM: Weekly like SAM\n\n'
            'At each visit:\n'
            '- Measure weight, height, MUAC\n'
            '- Check for oedema\n'
            '- Appetite test (RUTF)\n'
            '- Medical history (diarrhoea, vomiting, fever, cough)\n'
            '- Physical examination\n'
            '- Dispense RUTF/supplies\n'
            '- Record treatment response'
        )
    },
}


def get_fallback_response(user_message):
    """Generate a response using the rule-based knowledge base."""
    msg_lower = user_message.lower()

    for key, entry in FALLBACK_KNOWLEDGE.items():
        for kw in entry['keywords']:
            if kw in msg_lower:
                return entry['response']

    # Generic helpful response
    return (
        'I can help with CMAM clinical guidance. Try asking about:\n'
        '- SAM or MAM diagnosis and management\n'
        '- RUTF dosage and appetite testing\n'
        '- IPC referral criteria\n'
        '- Discharge criteria\n'
        '- Visit schedules\n'
        '- Oedema grading\n'
        '- Managing defaulters\n\n'
        'Please describe the patient situation for specific advice.'
    )


def chat_with_llm(messages, user=None):
    """
    Send chat messages to an LLM API and return the response.

    Uses OpenAI-compatible API if OPENAI_API_KEY is configured.
    Falls back to rule-based responses otherwise.

    Args:
        messages: list of {role, content} dicts
        user: User object (optional, for context)

    Returns:
        dict with 'response', 'source' ('llm' or 'fallback'), 'metadata'
    """
    api_key = _get_api_key()
    api_url = _get_api_url()
    model = _get_model()

    if not api_key:
        # Use fallback rule-based system
        last_user_msg = ''
        for msg in reversed(messages):
            if msg['role'] == 'user':
                last_user_msg = msg['content']
                break

        response = get_fallback_response(last_user_msg)
        return {
            'response': response,
            'source': 'fallback',
            'metadata': {'note': 'Using built-in CMAM knowledge base. Configure OPENAI_API_KEY for AI-powered responses.'}
        }

    # Call LLM API
    try:
        import requests

        # Build the full message list with system prompt
        full_messages = [
            {'role': 'system', 'content': CMAM_SYSTEM_PROMPT}
        ]

        # Add user context if available
        if user:
            user_context = f"\n\nCurrent user: {user.name}, Role: {getattr(user, 'role', {}).get('name', 'Unknown') if isinstance(getattr(user, 'role', None), dict) else 'Healthcare Worker'}"
            full_messages[0]['content'] += user_context

        # Add conversation history (last 10 messages)
        full_messages.extend(messages[-10:])

        payload = {
            'model': model,
            'messages': full_messages,
            'max_tokens': 800,
            'temperature': 0.3,
        }

        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }

        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        ai_response = data['choices'][0]['message']['content']

        return {
            'response': ai_response,
            'source': 'llm',
            'metadata': {
                'model': model,
                'usage': data.get('usage', {}),
            }
        }

    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        last_user_msg = ''
        for msg in reversed(messages):
            if msg['role'] == 'user':
                last_user_msg = msg['content']
                break

        response = get_fallback_response(last_user_msg)
        return {
            'response': response,
            'source': 'fallback',
            'metadata': {'error': str(e), 'note': 'LLM API unavailable, using built-in knowledge base.'}
        }


def _get_api_key():
    """Get OpenAI API key from Django settings/env."""
    from django.conf import settings
    return getattr(settings, 'OPENAI_API_KEY', None) or __import__('os').environ.get('OPENAI_API_KEY', '')


def _get_api_url():
    """Get the LLM API URL."""
    from django.conf import settings
    return getattr(settings, 'OPENAI_API_URL', 'https://api.openai.com/v1/chat/completions')


def _get_model():
    """Get the LLM model name."""
    from django.conf import settings
    return getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
