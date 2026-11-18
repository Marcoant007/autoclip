"""Vector 2D animation engine (Skia): articulated rigs, painted sets, lip sync.

Everything here is drawn locally from code. ``skia-python`` provides anti-aliased
Bézier paths, gradients, blur and path boolean operations, which the older
Pillow puppet renderer in ``pipeline/cartoon.py`` cannot express.
"""
