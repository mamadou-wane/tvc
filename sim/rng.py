GOLDEN = 0x9E3779B97F4A7C15
MASK = 0xFFFFFFFFFFFFFFFF
MIX1 = 0xBF58476D1CE4E5B9
MIX2 = 0x94D049BB133111EB
TWO_M53 = 1.0 / 9007199254740992.0

STREAMS = (
    "link.loss.up",
    "link.loss.down",
    "sensor.noise",
    "actuator.fault",
    "environment.disturbance",
    "parameter.sampling",
    "scenario",
)


def _mix(value: int) -> int:
    value &= MASK
    value = ((value ^ (value >> 30)) * MIX1) & MASK
    value = ((value ^ (value >> 27)) * MIX2) & MASK
    return value ^ (value >> 31)


def stream_state(master: int, name: str) -> int:
    index = STREAMS.index(name)
    return _mix((master + (index + 1) * GOLDEN) & MASK)


class SplitMix64:
    def __init__(self, state: int):
        self.state = state & MASK

    def next_u64(self) -> int:
        self.state = (self.state + GOLDEN) & MASK
        return _mix(self.state)

    def next_double(self) -> float:
        return (self.next_u64() >> 11) * TWO_M53
