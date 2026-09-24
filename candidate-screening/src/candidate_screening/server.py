"""Run the screening API with its port loaded from service settings."""

import argparse

import uvicorn

from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the candidate screening API")
    parser.add_argument("--reload", action="store_true", help="reload on code changes")
    args = parser.parse_args()
    uvicorn.run(
        "candidate_screening.api:app",
        host="127.0.0.1",
        port=Settings().api_port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
