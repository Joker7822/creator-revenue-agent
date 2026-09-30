import argparse
import json

from app.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["plan", "publish", "metrics"],
        default="plan",
    )
    parser.add_argument("--job-id")
    parser.add_argument("--window", default="7d")
    args = parser.parse_args()

    agent = Orchestrator()

    if args.mode == "plan":
        result = agent.create_job(
            {
                "campaign_type": "members_only_release",
                "target_segment": "subscribers",
                "price_cents": 1500,
            }
        )
    elif args.mode == "publish":
        if not args.job_id:
            raise SystemExit("--job-id is required for publish mode")
        result = agent.publish_if_approved(args.job_id)
    else:
        result = agent.metrics(window=args.window)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
