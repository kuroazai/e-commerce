"""Perceptual hashing.

A cryptographic hash is useless here: two photos of the same card differ in every
byte. A perceptual hash is built from low-frequency image structure, so it stays
close under lighting changes, mild blur and JPEG compression, and far apart for
genuinely different artwork.

pHash (DCT-based) rather than average-hash because it tolerates brightness and
contrast shifts, which is most of what varies between a scan and a phone photo.
"""
from __future__ import annotations

import cv2
import numpy as np

#: 32x32 reduced to the top-left 8x8 of the DCT gives 64 bits - enough to
#: separate tens of thousands of cards while staying robust to noise.
DCT_SIZE = 32
HASH_SIDE = 8
HASH_BITS = HASH_SIDE * HASH_SIDE


def phash(image: np.ndarray) -> int:
    """64-bit perceptual hash of a (dewarped) card image."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(gray, (DCT_SIZE, DCT_SIZE), interpolation=cv2.INTER_AREA)
    # astype, not np.float32(...): the latter is typed as a scalar constructor
    # and only happens to accept an array.
    coefficients = cv2.dct(small.astype(np.float32))
    block = coefficients[:HASH_SIDE, :HASH_SIDE]

    # The DC term carries overall brightness and would dominate the median, so
    # it is excluded from the threshold while still occupying a bit.
    # asarray with an explicit dtype: cv2.dct is typed as returning either an
    # integer or a floating array, and np.median does not accept that union.
    median = float(np.median(np.asarray(block, dtype=np.float32).flatten()[1:]))

    bits = 0
    for value in block.flatten():
        bits = (bits << 1) | int(value > median)
    return bits


def hamming(left: int, right: int) -> int:
    """Number of differing bits. This is the distance metric for matching."""
    return int(bin(left ^ right).count("1"))


def similarity(left: int, right: int) -> float:
    """1.0 for identical, 0.0 for maximally different."""
    return 1.0 - hamming(left, right) / HASH_BITS


def region_hashes(image: np.ndarray) -> tuple[int, int, int]:
    """Hashes of the full card, the artwork box and the name bar.

    One hash over the whole card struggles with alternate-art and reprint
    variants, which share a layout and differ mainly in the artwork. Hashing the
    regions separately lets the matcher weigh "same name, different art" against
    "different card" instead of collapsing them.

    The fractions are the standard Yu-Gi-Oh frame layout.
    """
    height, width = image.shape[:2]
    name_bar = image[int(height * 0.04):int(height * 0.12), int(width * 0.06):int(width * 0.80)]
    artwork = image[int(height * 0.15):int(height * 0.55), int(width * 0.12):int(width * 0.88)]
    return phash(image), phash(artwork), phash(name_bar)
