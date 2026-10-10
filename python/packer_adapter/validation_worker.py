"""One bounded independent validation, isolated so callers can terminate it."""
import json
import sys

from .validation import validate


def main():
    limit = 5 * 1024 * 1024
    raw = sys.stdin.buffer.read(limit+1)
    if len(raw) > limit:
        raise ValueError('Validation input exceeds 5 MiB')
    pair = json.loads(raw)
    errors = validate(pair['request'], pair['result'], diagnostics=True)
    sys.stdout.write(json.dumps({'errors': errors}, ensure_ascii=True, allow_nan=False))


if __name__ == '__main__':
    main()
