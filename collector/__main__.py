"""Запуск: python -m collector discover | track"""
import sys

from .jobs import discover, track

COMMANDS = {"discover": discover, "track": track}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        raise SystemExit("Использование: python -m collector [discover|track]")
    COMMANDS[sys.argv[1]]()
