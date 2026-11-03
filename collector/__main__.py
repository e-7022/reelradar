"""Запуск: python -m collector discover | track | rescore"""
import sys

from .jobs import discover, rescore, track

COMMANDS = {"discover": discover, "track": track, "rescore": rescore}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("Использование: python -m collector [discover|track|rescore]")
    COMMANDS[sys.argv[1]]()
