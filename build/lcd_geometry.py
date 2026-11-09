"""Approximate MS-70CDR pixel height/width, calibrated from hardware photos.

128x64 is the bitmap, not a 2:1 physical display. Allow a few percent camera
perspective error; hardware verification remains the final reference.
"""
PIXEL_ASPECT = 1.4
