"""EnvForge release QA and reproducible local episode CLI."""

import argparse
import json
import os
from pathlib import Path

from envforge.client import evaluate_http_agent
from envforge.protocol.types import DifficultyTier, SuiteName
from envforge.qa import run_qa, solve


def main() -> None:
    parser = argparse.ArgumentParser(prog="envforge")
    commands = parser.add_subparsers(dest="command", required=True)
    smoke = commands.add_parser("smoke", help="Run the explicit oracle baseline")
    smoke.add_argument("--seed", type=int, default=42)
    qa = commands.add_parser("qa", help="Run release QA gates and export the manifest")
    qa.add_argument("--instances", type=int, default=50)
    qa.add_argument("--repeats", type=int, default=20)
    qa.add_argument("--output", type=Path)
    evaluate = commands.add_parser(
        "evaluate", help="Evaluate a customer HTTP agent through the control plane"
    )
    evaluate.add_argument("--api-url", default="http://127.0.0.1:8000")
    evaluate.add_argument("--agent-url", required=True)
    evaluate.add_argument(
        "--suite", choices=[s.value for s in SuiteName], default="smoke"
    )
    evaluate.add_argument(
        "--tier", choices=[t.value for t in DifficultyTier], default="easy"
    )
    evaluate.add_argument("--episodes", type=int, default=10)
    evaluate.add_argument("--seed", type=int, default=42)
    evaluate.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "evaluate":
        if not 1 <= args.episodes <= 500:
            parser.error("episodes must be 1..500")
        result = evaluate_http_agent(
            args.api_url,
            args.agent_url,
            os.environ.get("ENVFORGE_API_TOKEN", ""),
            suite=args.suite,
            tier=args.tier,
            episodes=args.episodes,
            seed=args.seed,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "evaluation_id": result["evaluation_id"],
                    "status": result["status"],
                    "metrics": result["metrics"],
                },
                indent=2,
            )
        )
        raise SystemExit(
            0
            if result["status"] == "COMPLETED"
            and result["metrics"]["success_rate"] == 1
            else 1
        )
    if args.command == "smoke":
        _, result = solve(args.seed, SuiteName.SMOKE, DifficultyTier.EASY)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result["success"] else 1)
    if not 1 <= args.instances <= 500 or not 1 <= args.repeats <= 100:
        parser.error("instances must be 1..500 and repeats 1..100")
    result = run_qa(args.instances, args.repeats)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "instances"},
            indent=2,
        )
    )
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
