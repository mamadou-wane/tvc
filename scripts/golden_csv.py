"""Extract the frozen harness columns; timestamps are deliberately excluded."""
import argparse
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ground import wire


def harness_csv(records) -> str:
    lines = ['tick,theta,cmd']
    for record in records:
        words = [f'0x{struct.unpack("<Q", struct.pack("<d", value))[0]:016x}'
                 for value in (record.theta, record.cmd)]
        lines.append(','.join([str(record.tick), *words]))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--columns', required=True, choices=['tick,theta,cmd'])
    parser.add_argument('recording')
    args = parser.parse_args(argv)
    try:
        _, records, counters = wire.read_typed_recording(args.recording, expected_type=1)
        if any(value for key, value in counters.items() if key != 'frames_ok'):
            raise ValueError('recording has framing or sequence errors')
        if any(record['drops'] for record in records):
            raise ValueError('recording has ring drops')
        print(harness_csv([wire.Record(**record) for record in records]), end='')
    except (OSError, ValueError) as error:
        print(f'golden_csv: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
