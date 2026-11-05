"""Precise sleeps on Windows.

Windows' default timer tick is 15.6 ms, so sleep()/select()/SDL_Delay round
up to it: a 60 fps frame limiter ends up near 30 fps and a 30 Hz server tick
becomes irregular. timeBeginPeriod(1) requests 1 ms resolution for this
process (released automatically when the process exits).
"""
import sys


def high_res_timer():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
    except (OSError, AttributeError):
        pass
