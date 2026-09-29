"""Start the combined application with one public API port."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the combined Sieve API")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("sieve_app.api:app", host="127.0.0.1", port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
