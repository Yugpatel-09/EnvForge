"""Private JSON stdin/stdout verifier worker; never exposed as an agent tool."""

import json
import sys

from envforge.protocol.types import ImmutableStateReference
from envforge.worlds.sre.verifier.verifier import SREVerifier


def main() -> None:
    payload = json.load(sys.stdin)
    result = SREVerifier().verify(
        ImmutableStateReference.model_validate(payload["reference"]), payload["truth"]
    )
    print(result.model_dump_json())


if __name__ == "__main__":
    main()
