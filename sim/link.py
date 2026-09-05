from sim.rng import SplitMix64


def draw_drop(stream: SplitMix64, p: float) -> bool:
    if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0.0 <= p <= 1.0:
        raise ValueError("probability must be a finite number in [0, 1]")
    u = stream.next_double()
    return u < p
