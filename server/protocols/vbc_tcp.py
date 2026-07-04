import re
import socket
from collections import defaultdict, deque

from server import app
from server.models import FlagStatus, SubmitResult


READ_TIMEOUT = 5
GREETING_TIMEOUT = 5
MAX_LINE = 65536

# Format: "<flag> <CODE> [message]"
RESPONSE_RE = re.compile(r'^(\S+)\s+([A-Z]{2,3})(?:\s+(.*))?$')

STATUS_BY_CODE = {
    'OK': FlagStatus.ACCEPTED,
    'DUP': FlagStatus.REJECTED,
    'OWN': FlagStatus.REJECTED,
    'OLD': FlagStatus.REJECTED,
    'INV': FlagStatus.REJECTED,
    # Competition not started / already ended. Retry later in line with other
    # protocols where temporary checksystem failures are requeued.
    'ERR': FlagStatus.QUEUED,
}


def _recv_until_double_newline(sock):
    sock.settimeout(GREETING_TIMEOUT)
    data = bytearray()

    while b'\n\n' not in data and len(data) < MAX_LINE:
        chunk = sock.recv(1024)
        if not chunk:
            break
        data.extend(chunk)

    sock.settimeout(READ_TIMEOUT)
    return bytes(data)


def _recv_line(sock):
    data = bytearray()
    while len(data) < MAX_LINE:
        chunk = sock.recv(1)
        if not chunk:
            break
        data.extend(chunk)
        if chunk == b'\n':
            break

    if not data:
        return None

    return bytes(data)


def _parse_response_line(line):
    text = line.decode(errors='replace').strip()
    m = RESPONSE_RE.match(text)
    if not m:
        return None, FlagStatus.QUEUED, text

    flag, code, message = m.groups()
    status = STATUS_BY_CODE.get(code, FlagStatus.QUEUED)
    return flag, status, text if message is None else '{} {} {}'.format(flag, code, message)


def submit_flags(flags, config):
    if not flags:
        return

    sock = socket.create_connection((config['SYSTEM_HOST'], config['SYSTEM_PORT']), READ_TIMEOUT)
    try:
        greeting = _recv_until_double_newline(sock)
        if b'\n\n' not in greeting:
            raise Exception('Checksystem greeting is incomplete: {}'.format(greeting))

        payload = ''.join(item.flag + '\n' for item in flags).encode()
        sock.sendall(payload)

        pending_by_flag = defaultdict(deque)
        for idx, item in enumerate(flags):
            pending_by_flag[item.flag].append(idx)

        results = [SubmitResult(item.flag, FlagStatus.QUEUED, 'No response from checksystem')
                   for item in flags]
        unknown_lines = set()

        for _ in range(len(flags)):
            line = _recv_line(sock)
            if line is None:
                break

            response_flag, status, response_text = _parse_response_line(line)
            if response_flag is None and response_text not in unknown_lines:
                unknown_lines.add(response_text)
                app.logger.warning('Unknown checksystem response (flag will be resent): %s', response_text)

            if response_flag is not None and pending_by_flag[response_flag]:
                idx = pending_by_flag[response_flag].popleft()
            else:
                idx = None
                for i, item in enumerate(results):
                    if item.checksystem_response == 'No response from checksystem':
                        idx = i
                        break

                if idx is None:
                    continue

            results[idx] = SubmitResult(flags[idx].flag, status, response_text)

        for item in results:
            yield item
    finally:
        sock.close()