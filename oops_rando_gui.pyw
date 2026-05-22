#!/usr/bin/env pythonw
"""Launcher for users who double-click instead of running from a terminal.

Windows associates .pyw files with pythonw.exe (the windowed Python
interpreter), which doesn't allocate a console. Double-clicking this
file on Windows opens the GUI directly with no command-prompt flash.

For terminal users on Windows who still see a console window, run
the GUI with pythonw instead of python:
    pythonw .\\oops_rando_gui.py

For diagnostic output (the [gui] startup prints used during hang
investigations), keep using python which preserves stdout/stderr:
    python .\\oops_rando_gui.py
"""
import os
import sys

# Re-exec via the same Python that found this .pyw, importing the
# main .py module. Keeps the codebase single-source: any change to
# oops_rando_gui.py applies to both launch paths.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import oops_rando_gui
oops_rando_gui.main()
