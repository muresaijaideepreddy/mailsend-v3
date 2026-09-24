"""Source checks independent of the model's claimed message/body boundaries."""
import re
from datetime import datetime
from email.utils import getaddresses

HEADER = re.compile(r'^\s*(To|CC|BCC|Subject|Date|Send on|Send date|From):\s*(.*)$', re.I)
HEADING = re.compile(r'^\s*(?:message|email|draft)\s*#?\s*\d+\s*[:.)-]?\s*$', re.I)
START = re.compile(r'^\s*(?:BEGIN\s+)?EMAIL DRAFT\s*$', re.I)
END = re.compile(r'^\s*END EMAIL DRAFT\s*$', re.I)


def ignorable(line):
    return not line.strip() or line.strip() == '[credential removed]' or bool(HEADING.fullmatch(line) or START.fullmatch(line) or END.fullmatch(line))


def source_fields(source_lines):
    """Read only the leading header block; quoted/body headers are body text."""
    headers = {}
    body_start = 0
    found = False
    for index, line in enumerate(source_lines):
        if ignorable(line):
            body_start = index + 1
            continue
        match = HEADER.match(line)
        if match:
            found = True
            key = match[1].lower()
            key = 'date' if key in ('send on', 'send date') else key
            headers.setdefault(key, []).append(match[2].strip())
            body_start = index + 1
            continue
        # Everything after the first body line belongs to the body, including
        # lines that happen to look like forwarded message headers.
        break
    return headers, source_lines[body_start:] if found else source_lines


def source_date(value):
    value = value.strip()
    for fmt in ('%Y-%m-%d', '%B %d, %Y', '%b %d, %Y', '%d %B %Y', '%d %b %Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def check_source_fields(row, source_lines, parse_addresses, error):
    headers, body_lines = source_fields(source_lines)
    normalize = lambda value: ' '.join(value.split())
    for field in ('to', 'cc', 'bcc'):
        source = ', '.join(headers.get(field, []))
        try:
            expected = parse_addresses(source)
        except Exception:
            # Invalid original recipient text is retained by the importer for
            # manual review. It is never an authority for a valid replacement.
            expected = ''
        try:
            actual = parse_addresses(row[field])
        except Exception:
            actual = ''
        addresses = lambda value: {address.casefold() for _, address in getaddresses([value]) if address}
        if addresses(actual) != addresses(expected):
            raise error('recipient fields differ from their source headers; review the document recipient lines')
    expected_subject = ' '.join(headers.get('subject', []))
    if normalize(row['subject']) != normalize(expected_subject):
        raise error('the subject differs from its source header')
    expected_date = source_date(' '.join(headers.get('date', [])))
    actual_date = source_date(row['send_date']) if row['send_date'] else None
    if actual_date != expected_date or (row['send_date'] and actual_date is None):
        raise error('the date is not supported by its source header')
    # Redacted credentials are intentionally excluded. Other source text must
    # not disappear, even when the model chooses a shorter body range.
    expected_body = '\n'.join(line for line in body_lines if line.strip() != '[credential removed]' and not END.fullmatch(line))
    if normalize(row['body']) != normalize(expected_body):
        raise error('the body was changed or omitted source text; check message boundaries')


def check_coverage(rows, lines, used, error):
    if not rows:
        if any(HEADER.match(line) for line in lines):
            raise error('no drafts were returned despite message headers in the source')
        return
    marked, opened = set(), None
    for i, line in enumerate(lines, 1):
        if START.fullmatch(line):
            if opened is not None:
                raise error('message boundary markers are nested or incomplete')
            opened = i
        elif END.fullmatch(line):
            if opened is None:
                raise error('message boundary markers are nested or incomplete')
            marked.update(range(opened, i + 1))
            opened = None
    if opened is not None:
        raise error('message boundary markers are nested or incomplete')
    if marked:
        required = marked | {i for i, line in enumerate(lines, 1) if HEADER.match(line)}
        if any(i not in used and not ignorable(lines[i - 1]) for i in required):
            raise error('source text was left outside the extracted messages; split or clarify message boundaries')
        return
    # Leading document notes may precede the first message. Once messages
    # begin, unexplained text is rejected rather than silently dropped.
    first = min(row['start_line'] for row in rows)
    leading_headers = [i + 1 for i, line in enumerate(lines[:first - 1]) if HEADER.match(line)]
    if leading_headers:
        first = min(leading_headers)
    if any(i not in used and not ignorable(line)
           for i, line in enumerate(lines, 1) if i >= first):
        raise error('source text was left outside the extracted messages; split or clarify message boundaries')
