#!/usr/bin/env python3
import os  # Set DJANGO_SETTINGS_MODULE before Django boots.
import sys  # Forward CLI argv into Django's management runner.

if __name__ == "__main__":  # Only run when executed as a script, not imported.
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ciutils.settings")  # Default settings for all commands.
    from django.core.management import execute_from_command_line  # Django CLI entry (migrate, runserver, …).
    execute_from_command_line(sys.argv)  # Parse argv and run the requested management command.
