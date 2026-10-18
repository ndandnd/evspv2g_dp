"""Streamed compaction of a pretty-printed (indent=2) result.json.

Every scalar and every list of at most MAX_LINES pretty-printed lines is kept verbatim.
A longer list (CG traces such as rmp_calls/pricing_calls, path witnesses) is replaced by
{"_omitted_list": true, "elements": N, "pretty_lines": M}. The SHA-256 and size of the
original file are stored under "_compaction", so the extract stays bound to the original.
The original is read once, line by line, and never loaded whole into memory.
"""
import hashlib, json, sys

MAX_LINES = 400


def _indent(b):
    return len(b) - len(b.lstrip(b' '))


def compact(src, dst):
    h = hashlib.sha256(); nbytes = 0
    out = []                     # kept lines (bytes) at top level
    stack = []                   # open list frames
    omitted = []
    for lineno, raw in enumerate(open(src, 'rb'), 1):
        h.update(raw); nbytes += len(raw)
        line = raw.rstrip(b'\n')
        ind = _indent(line); s = line.lstrip(b' ')
        top = stack[-1] if stack else None
        if top is not None and top['skip']:
            if ind == top['indent'] and s in (b']', b'],'):
                key = top['open'].lstrip(b' ')[:-1].rstrip()          # '"key":' or ''
                stub = b' ' * top['indent'] + key + (b' ' if key else b'') + json.dumps(
                    {'_omitted_list': True, 'elements': top['n'], 'pretty_lines': top['lines'] + 1}).encode() + (b',' if s.endswith(b',') else b'')
                omitted.append({'key': key.decode()[:-1].strip('"') if key else None, 'elements': top['n'], 'line': top['line']})
                stack.pop()
                (stack[-1]['buf'] if stack else out).append(stub)
                if stack: _check(stack[-1])
                continue
            top['lines'] += 1
            if top['child'] is None and ind > top['indent']: top['child'] = ind
            if ind == top['child'] and not s.startswith((b']', b'}')): top['n'] += 1
            continue
        if top is not None:
            if top['child'] is None and ind > top['indent']: top['child'] = ind
            if ind == top['child'] and not s.startswith((b']', b'}')): top['n'] += 1
        if s.endswith(b'['):
            stack.append({'indent': ind, 'open': line, 'buf': [line], 'lines': 0, 'n': 0, 'child': None, 'skip': False, 'line': lineno})
            continue
        if top is not None and ind == top['indent'] and s in (b']', b'],'):
            top['buf'].append(line); stack.pop()
            (stack[-1]['buf'] if stack else out).extend(top['buf'])
            if stack: _check(stack[-1])
            continue
        if top is not None:
            top['buf'].append(line); top['lines'] += 1; _check(top)
        else:
            out.append(line)
    if stack: raise ValueError(f'{src}: unbalanced list structure')
    data = json.loads(b'\n'.join(out))
    data['_compaction'] = {'source_bytes': nbytes, 'source_sha256': h.hexdigest(), 'max_lines_kept_per_list': MAX_LINES,
                           'omitted_lists': omitted, 'tool': 'tools/compact_result.py'}
    with open(dst, 'w') as f: json.dump(data, f, indent=1)
    return nbytes, h.hexdigest(), len(omitted)


def _check(frame):
    if not frame['skip'] and len(frame['buf']) > MAX_LINES:
        frame['lines'] = len(frame['buf']) - 1; frame['buf'] = [frame['open']]; frame['skip'] = True


if __name__ == '__main__':
    print(compact(sys.argv[1], sys.argv[2]))
