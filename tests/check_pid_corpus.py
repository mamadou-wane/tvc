"""Feed the frozen PID literals to the C++ test, including rejection proofs."""

import json
from pathlib import Path
import re
import subprocess
import sys


CONSTANT_NAMES = (
    "KP", "KI", "KD", "DT", "KI_DT", "BETA_D", "DELTA_MAX", "I_MAX", "THETA_SP",
)
SUCCESS = b"control_tests: corpus ok constants=9 vectors=12 traces=3 calls=22\n"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def fields(value, names):
    require(isinstance(value, dict) and set(value) == set(names),
            f"expected object fields: {names}")


def words(value, count):
    require(isinstance(value, list) and len(value) == count,
            f"expected {count} bit words")
    require(all(isinstance(word, str) and re.fullmatch(r"0x[0-9a-f]{16}", word)
                for word in value), "malformed binary64 word")
    return value


def protocol(document):
    fields(document, ("constants_bits", "digest_crc32c", "vectors", "traces"))
    require(document["digest_crc32c"] == "0xe77201ca", "unexpected digest metadata")
    constants = document["constants_bits"]
    fields(constants, CONSTANT_NAMES)
    lines = [f"CONST {name} {words([constants[name]], 1)[0]}"
             for name in CONSTANT_NAMES]
    vectors = document["vectors"]
    require(isinstance(vectors, list) and len(vectors) == 12, "expected 12 vectors")
    for index, vector in enumerate(vectors, 1):
        fields(vector, ("id", "state_bits", "observation_bits", "expected_bits"))
        name = f"V{index:02d}"
        require(vector["id"] == name, f"expected vector {name}")
        values = (words(vector["state_bits"], 3)
                  + words(vector["observation_bits"], 2)
                  + words(vector["expected_bits"], 4))
        lines.append(" ".join(["VECTOR", name, *values]))
    traces = document["traces"]
    require(isinstance(traces, list) and len(traces) == 3, "expected 3 traces")
    for index, (trace, length) in enumerate(zip(traces, (3, 3, 4)), 1):
        fields(trace, ("id", "initial_state_bits", "steps"))
        name = f"T{index}"
        require(trace["id"] == name, f"expected trace {name}")
        lines.append(" ".join(["TRACE", name, *words(trace["initial_state_bits"], 3)]))
        steps = trace["steps"]
        require(isinstance(steps, list) and len(steps) == length,
                f"expected {length} steps for {name}")
        for number, step in enumerate(steps, 1):
            fields(step, ("observation_bits", "expected_bits"))
            values = words(step["observation_bits"], 2) + words(step["expected_bits"], 4)
            lines.append(" ".join(["STEP", str(number), *values]))
    lines.append("END")
    require(len(lines) == 35, "expected 35 protocol records")
    return lines


def encoded(lines):
    return ("\n".join(lines) + "\n").encode("ascii")


def run(binary, data):
    return subprocess.run([str(binary), "--corpus-stdin"], input=data,
                          capture_output=True, timeout=30, check=False)


def negative_checks(binary, lines):
    # Alter only supplied expectation data, never the frozen artifact.
    corrupted = lines.copy()
    vector = corrupted[9].split()
    require(vector[:2] == ["VECTOR", "V01"] and vector[7] == "0x0000000000000000",
            "V01 corruption probe precondition failed")
    vector[7] = "0x0000000000000001"
    corrupted[9] = " ".join(vector)
    result = run(binary, encoded(corrupted))
    diagnostic = (b"V01[0] delta: got 0x0000000000000000, "
                  b"expected 0x0000000000000001")
    require(result.returncode == 1 and SUCCESS not in result.stdout
            and SUCCESS not in result.stderr and diagnostic in result.stderr,
            f"corrupted V01 did not produce the required mismatch: {result}")

    valid = encoded(lines)
    duplicate = lines.copy()
    duplicate[10] = duplicate[9]
    reordered = lines.copy()
    reordered[9], reordered[10] = reordered[10], reordered[9]
    unexpected = lines.copy()
    unexpected[21] = unexpected[21].replace("TRACE T1", "TRACE T4")
    malformed = lines.copy()
    malformed[0] = "CONST KP 0x400A374bc6a7ef9e"
    cases = (
        ("empty", b""),
        ("missing constant", encoded(lines[1:])),
        ("duplicate vector", encoded(duplicate)),
        ("reordered vector", encoded(reordered)),
        ("unexpected trace", encoded(unexpected)),
        ("malformed word", encoded(malformed)),
        ("missing final step", encoded(lines[:-2] + ["END"])),
        ("missing END", encoded(lines[:-1])),
        ("unterminated END", valid[:-1]),
        ("trailing data", valid + b"END\n"),
        ("blank line", b"\n" + valid),
        ("comment", b"# corpus\n" + valid),
        ("CR", valid.replace(b"\n", b"\r\n", 1)),
        ("extra field", valid.replace(b"CONST KP ", b"CONST KP extra ", 1)),
    )
    for name, data in cases:
        result = run(binary, data)
        require(result.returncode == 2 and SUCCESS not in result.stdout
                and SUCCESS not in result.stderr,
                f"{name} did not produce protocol rejection: {result}")


def main():
    if len(sys.argv) != 2:
        print("usage: check_pid_corpus.py CONTROL_TESTS_BINARY", file=sys.stderr)
        return 2
    try:
        binary = Path(sys.argv[1]).resolve()
        corpus = Path(__file__).resolve().parent / "golden" / "pid" / "pid_corpus.json"
        document = json.loads(corpus.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_object)
        lines = protocol(document)
        result = run(binary, encoded(lines))
        require(result.returncode == 0 and result.stdout == SUCCESS,
                f"positive corpus completion failed: {result}")
        negative_checks(binary, lines)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"check_pid_corpus: {error}", file=sys.stderr)
        return 1
    print("check_pid_corpus: ok constants=9 vectors=12 traces=3 calls=22; "
          "negative checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
