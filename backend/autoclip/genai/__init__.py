"""Local generative models: scene illustrations (SDXL) and image-to-video (Wan 2.2).

Everything runs on this computer's GPU. Heavy imports (torch, diffusers) happen
lazily inside functions, so the rest of AutoClip works without them installed.
"""
