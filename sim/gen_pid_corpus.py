"""Serialize the frozen PID oracle without running a controller."""

import argparse
import json
import os
from pathlib import Path


# Contract literals are deliberately independent of the controller and tests.
_DOCUMENT = {
    "constants_bits": {
        "KP": "0x400a374bc6a7ef9e",
        "KI": "0x401eb851eb851eb8",
        "KD": "0x3fd3c6a7ef9db22d",
        "DT": "0x3f60624dd2f1a9fc",
        "KI_DT": "0x3f8f75104d551d69",
        "BETA_D": "0x3fd5555555555555",
        "DELTA_MAX": "0x3fbeb851eb851eb8",
        "I_MAX": "0x3fbeb851eb851eb8",
        "THETA_SP": "0x0000000000000000",
    },
    "digest_crc32c": "0xe77201ca",
    "vectors": [
        {
            "id": "V01",
            "state_bits": ["0x0000000000000000","0x0000000000000000","0x0000000000000000"],
            "observation_bits": ["0x0000000000000000","0x0000000000000000"],
            "expected_bits": ["0x0000000000000000","0x0000000000000000","0x0000000000000000","0x0000000000000000"],
        },
        {
            "id": "V02",
            "state_bits": ["0xbf2f75104d551d69","0x0000000000000000","0x3fb0000000000000"],
            "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
            "expected_bits": ["0x3faa374bc6a7ef9e","0x0000000000000000","0x0000000000000000","0x3faa374bc6a7ef9e"],
        },
        {
            "id": "V03",
            "state_bits": ["0x0000000000000000","0x3fd0000000000000","0x3fb0000000000000"],
            "observation_bits": ["0x3f80000000000000","0xbfc0000000000000"],
            "expected_bits": ["0x3fb079042d8c2a45","0x3f1f75104d551d69","0x3fc0000000000000","0x3fb079042d8c2a45"],
        },
        {
            "id": "V04",
            "state_bits": ["0xbfa0000000000000","0x3fb0000000000000","0x3fb0000000000000"],
            "observation_bits": ["0xbfb0000000000000","0xbfe0000000000000"],
            "expected_bits": ["0xbfbeb851eb851eb8","0xbfa0000000000000","0xbfc0000000000000","0xbfbeb851eb851eb8"],
        },
        {
            "id": "V05",
            "state_bits": ["0x3fbeb851eb851eb8","0x0000000000000000","0x3fbeb851eb851eb8"],
            "observation_bits": ["0xbf90000000000000","0x3ff8000000000000"],
            "expected_bits": ["0x3fbeb851eb851eb8","0x3fbea897635e7429","0x3fe0000000000000","0x3fbeb851eb851eb8"],
        },
        {
            "id": "V06",
            "state_bits": ["0x3fbeb851eb851eb8","0xbfc8000000000000","0x3fa0000000000000"],
            "observation_bits": ["0x3f90000000000000","0xbfc8000000000000"],
            "expected_bits": ["0x3fbcfef9db22d0e6","0x3fbeb851eb851eb8","0xbfc8000000000000","0x3fbcfef9db22d0e6"],
        },
        {
            "id": "V07",
            "state_bits": ["0xbfbeb851eb851eb8","0x3fc8000000000000","0xbfa0000000000000"],
            "observation_bits": ["0xbf90000000000000","0x3fc8000000000000"],
            "expected_bits": ["0xbfbcfef9db22d0e6","0xbfbeb851eb851eb8","0x3fc8000000000000","0xbfbcfef9db22d0e6"],
        },
        {
            "id": "V08",
            "state_bits": ["0x3fb18cf1800a7c59","0x0000000000000000","0x0000000000000000"],
            "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
            "expected_bits": ["0x3fbeb851eb851eb7","0x3fb19cac083126e8","0x0000000000000000","0x3fbeb851eb851eb7"],
        },
        {
            "id": "V09",
            "state_bits": ["0x3fb18cf1800a7c5a","0x0000000000000000","0x0000000000000000"],
            "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
            "expected_bits": ["0x3fbeb851eb851eb8","0x3fb19cac083126e9","0x0000000000000000","0x3fbeb851eb851eb8"],
        },
        {
            "id": "V10",
            "state_bits": ["0x3fb18cf1800a7c5b","0x0000000000000000","0x0000000000000000"],
            "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
            "expected_bits": ["0x3fbeb851eb851eb8","0x3fb18cf1800a7c5b","0x0000000000000000","0x3fbeb851eb851eb8"],
        },
        {
            "id": "V11",
            "state_bits": ["0xbfb18cf1800a7c5a","0x0000000000000000","0x0000000000000000"],
            "observation_bits": ["0xbf90000000000000","0x0000000000000000"],
            "expected_bits": ["0xbfbeb851eb851eb8","0xbfb19cac083126e9","0x0000000000000000","0xbfbeb851eb851eb8"],
        },
        {
            "id": "V12",
            "state_bits": ["0x8000000000000000","0x8000000000000000","0xbfb0000000000000"],
            "observation_bits": ["0x8000000000000000","0x8000000000000000"],
            "expected_bits": ["0x0000000000000000","0x8000000000000000","0x0000000000000000","0x0000000000000000"],
        },
    ],
    "traces": [
        {
            "id": "T1",
            "initial_state_bits": ["0x0000000000000000","0x0000000000000000","0x0000000000000000"],
            "steps": [
                {
                    "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3faa56c0d6f544bb","0x3f2f75104d551d69","0x0000000000000000","0x3faa56c0d6f544bb"],
                },
                {
                    "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3faa7635e74299d9","0x3f3f75104d551d69","0x0000000000000000","0x3faa7635e74299d9"],
                },
                {
                    "observation_bits": ["0x3f90000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3faa95aaf78feef6","0x3f4797cc39ffd60f","0x0000000000000000","0x3faa95aaf78feef6"],
                },
            ],
        },
        {
            "id": "T2",
            "initial_state_bits": ["0x0000000000000000","0x0000000000000000","0x0000000000000000"],
            "steps": [
                {
                    "observation_bits": ["0x0000000000000000","0x3fd8000000000000"],
                    "expected_bits": ["0x3fa3c6a7ef9db22d","0x0000000000000000","0x3fc0000000000000","0x3fa3c6a7ef9db22d"],
                },
                {
                    "observation_bits": ["0x0000000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3f9a5e353f7ced92","0x0000000000000000","0x3fb5555555555556","0x3f9a5e353f7ced92"],
                },
                {
                    "observation_bits": ["0x0000000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3f9194237fa89e62","0x0000000000000000","0x3fac71c71c71c71e","0x3f9194237fa89e62"],
                },
            ],
        },
        {
            "id": "T3",
            "initial_state_bits": ["0x3fa0000000000000","0xbfb0000000000000","0xbfb0000000000000"],
            "steps": [
                {
                    "observation_bits": ["0x3fb0000000000000","0x3fe0000000000000"],
                    "expected_bits": ["0x3fbeb851eb851eb8","0x3fa0000000000000","0x3fc0000000000000","0x3fbeb851eb851eb8"],
                },
                {
                    "observation_bits": ["0x3fb0000000000000","0x0000000000000000"],
                    "expected_bits": ["0x3fbeb851eb851eb8","0x3fa0000000000000","0x3fb5555555555556","0x3fbeb851eb851eb8"],
                },
                {
                    "observation_bits": ["0xbf90000000000000","0x0000000000000000"],
                    "expected_bits": ["0xbf68caf1720f58a8","0x3f9fc115df6555c5","0x3fac71c71c71c71e","0xbf68caf1720f58a8"],
                },
                {
                    "observation_bits": ["0xbf90000000000000","0x0000000000000000"],
                    "expected_bits": ["0xbf8268a848299436","0x3f9f822bbecaab8a","0x3fa2f684bda12f6a","0xbf8268a848299436"],
                },
            ],
        },
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Serialize the fixed PID known answers.")
    parser.add_argument("output_directory", type=Path)
    output = parser.parse_args().output_directory
    if output.is_symlink() or not output.is_dir():
        parser.error("output_directory must be an existing, non-symlink directory")

    text = json.dumps(
        _DOCUMENT, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
    ) + "\n"

    # Anchor the write and reject symlinks at open time, not only during checks.
    directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        descriptor = os.open(
            "pid_corpus.json",
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o644,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as artifact:
            artifact.write(text.encode("utf-8"))
    finally:
        os.close(directory)


if __name__ == "__main__":
    main()
