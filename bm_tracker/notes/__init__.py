"""Achievements found by reading a note, rather than by counting one.

The only part of the app that calls out to a provider. Everything else is
countable, so this is isolated behind a small interface and a catalogue file:
adding an achievement is a TOML entry, and turning the whole thing off is
leaving a key out of the environment.
"""
