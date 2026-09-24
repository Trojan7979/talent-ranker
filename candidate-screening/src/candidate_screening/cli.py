import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Candidate screening background jobs")
    parser.add_argument("command", choices=["dispatch", "expire"])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    parser.error(f"{args.command} worker is not available until its implementation step")
