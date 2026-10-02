"""Card recognition from images.

    from cardshop.vision import CardIndex, CardScanner, fingerprint_reference

    index = CardIndex.load("reference.json")
    result = CardScanner(index).scan_file("photo.jpg")
    if result.needs_review:
        ...  # hand to a human or the agent
    else:
        print(result.best.card.name)

Detect the card in a photo, flatten it, fingerprint it perceptually, and match
against a reference index. No model download and no network.
"""
from .fingerprint import HASH_BITS, hamming, phash, region_hashes, similarity
from .index import CardIndex, Match, ReferenceCard
from .preprocess import CARD_HEIGHT, CARD_WIDTH, Detection, detect_card, dewarp, normalise_scan
from .scanner import CardScanner, ScanResult, fingerprint_reference

__all__ = [
    "phash", "hamming", "similarity", "region_hashes", "HASH_BITS",
    "CardIndex", "ReferenceCard", "Match",
    "detect_card", "dewarp", "normalise_scan", "Detection",
    "CARD_WIDTH", "CARD_HEIGHT",
    "CardScanner", "ScanResult", "fingerprint_reference",
]
