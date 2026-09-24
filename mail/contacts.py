"""Read-only Google contact lookup and local, reviewable name matching."""
import re
import unicodedata
from difflib import SequenceMatcher

import requests
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .google_api import CONTACTS_SCOPE, HTTP_TIMEOUT, _access_token
from .services import DeliveryRejected


def normalize_name(value):
    value = ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    words = re.findall(r'[^\W_]+', value, re.UNICODE)
    return ' '.join(w for w in words if w not in {'dr', 'prof', 'mr', 'mrs', 'ms'})


def contact_matches(name, contacts):
    query = normalize_name(name)
    if len(query) < 2 or query in {'unknown', 'team', 'everyone', 'all', 'sir', 'madam'}:
        return []
    results = {}
    for contact in contacts:
        candidate = normalize_name(contact['name'])
        if not candidate:
            continue
        if query == candidate or sorted(query.split()) == sorted(candidate.split()):
            score, reason = 1.0, 'Exact name'
        elif len(query.split()) == 1 and query in candidate.split():
            score, reason = .90, 'Partial name — review'
        else:
            score = max(SequenceMatcher(None, query, candidate).ratio(),
                        SequenceMatcher(None, ' '.join(sorted(query.split())), ' '.join(sorted(candidate.split()))).ratio())
            if len(query.split()) == 1 and len(query) >= 4:
                token_score = max(SequenceMatcher(None, query, word).ratio() for word in candidate.split())
                if token_score >= .85:
                    score = max(score, token_score * .90)
            reason = 'Similar spelling — review'
            if len(query) < 4 or score < .78:
                continue
        key = contact['email'].casefold()
        item = dict(contact, score=round(score * 100), reason=reason)
        if key not in results or item['score'] > results[key]['score']:
            results[key] = item
    return sorted(results.values(), key=lambda item: (-item['score'], item['name'], item['email']))[:10]


def fetch_contacts(user):
    token = _access_token(user, required_scopes=(CONTACTS_SCOPE,))
    contacts, page_token, seen = [], None, set()
    try:
        for _ in range(25):
            params = {'personFields': 'names,emailAddresses', 'pageSize': 1000}
            if page_token:
                params['pageToken'] = page_token
            with requests.get('https://people.googleapis.com/v1/people/me/connections',
                              headers={'Authorization': 'Bearer ' + token}, params=params,
                              timeout=HTTP_TIMEOUT, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise DeliveryRejected('Google contacts could not be read. Enable the People API and reconnect with contacts permission.')
                data = response.json()
            for person in data.get('connections', []):
                for name in person.get('names', []):
                    display = name.get('displayName', '')
                    if not isinstance(display, str) or not display.strip():
                        continue
                    for entry in person.get('emailAddresses', []):
                        email = entry.get('value', '')
                        try:
                            validate_email(email)
                            if not isinstance(email, str) or len(email) > 254 or re.search(r'[\s\x00-\x1f\x7f]', email):
                                continue
                        except (ValidationError, TypeError):
                            continue
                        contacts.append({'name': display[:255], 'email': email})
            page_token = data.get('nextPageToken')
            if not page_token:
                return contacts
            if not isinstance(page_token, str) or page_token in seen:
                break
            seen.add(page_token)
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise DeliveryRejected('Google contacts could not be read. Try again later.') from None
    raise DeliveryRejected('The contact list exceeds this lookup limit; no partial results were used.')


def suggested_name(message):
    names = []
    for line in message.imported_recipient_notes.splitlines():
        if line.strip().upper().startswith('TO:'):
            value = line.strip()[3:].strip()
            # An explicit unresolved address must not be replaced using a greeting.
            if '@' in value:
                return ''
            if value:
                names.append(value)
    match = re.match(r'\s*(?:dear|hi|hey|hello|howdy)\s+([^\n,!:]+)', message.body, re.I)
    greeting = match.group(1).strip() if match else ''
    if names:
        normalized = {tuple(sorted(normalize_name(name).split())) for name in names}
        if len(normalized) != 1:
            return ''
        return names[0][:100]
    return greeting[:100]


def enrich_import_recipients(user, rows):
    """Fill only uniquely exact missing To addresses; never send or change bodies."""
    from .models import Message
    pending = [row for row in rows if not row.get('to')]
    if not pending:
        return rows
    try:
        contacts = fetch_contacts(user)
    except DeliveryRejected:
        for row in pending:
            row['contact_match_notes'] = 'Contacts lookup unavailable. Recipient left blank; connect Google contacts or enter an address manually.'
        return rows
    for row in pending:
        name = suggested_name(Message(**row))
        candidates = contact_matches(name, contacts)
        exact = [item for item in candidates if item['score'] == 100 and item['reason'] == 'Exact name']
        # Invalid copied-recipient fields must still be reviewed. Do not bypass
        # the To-blank guard that the importer established for those fields.
        copied_review = any(line.startswith(('CC:', 'BCC:')) for line in row.get('imported_recipient_notes', '').splitlines())
        greeting = re.match(r'\s*(?:dear|hi|hey|hello|howdy)\s+([^\n,!:]+)', row.get('body', ''), re.I)
        # A conflicting greeting is useful evidence for review, not authority
        # to silently select either person's address.
        conflict = bool(greeting and name and
                        sorted(normalize_name(greeting.group(1)).split()) != sorted(normalize_name(name).split()))
        if len(exact) == 1 and not copied_review and not conflict:
            row['to'] = exact[0]['email']
            row['contact_match_notes'] = f"To filled from unique exact Google contact: {exact[0]['name']} <{exact[0]['email']}>. Review before sending."
        elif candidates:
            row['contact_match_notes'] = 'Recipient left blank for review. Contact suggestions for ' + name + ':\n' + '\n'.join(
                f"{item['name']} <{item['email']}> ({item['score']}% spelling similarity)" for item in candidates)
        else:
            row['contact_match_notes'] = 'No contact match for ' + (name or 'an identifiable recipient name') + '. Recipient left blank.'
    return rows
