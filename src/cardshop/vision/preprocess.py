"""Finding a card in a photo and flattening it.

A phone photo of a card on a desk is rotated, tilted and badly lit. Fingerprinting
that directly gives a different signature every time. So: find the card's outline,
perspective-correct it to a canonical rectangle, and fingerprint that instead.

Everything downstream assumes a dewarped card, which is why this runs first.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: Trading cards are 63x88mm. Canonical size keeps the aspect ratio and is big
#: enough for the DCT in the perceptual hash to see real detail.
CARD_WIDTH = 420
CARD_HEIGHT = 587
CARD_ASPECT = CARD_WIDTH / CARD_HEIGHT

#: A contour smaller than this fraction of the frame is noise, not a card.
MIN_AREA_FRACTION = 0.05
#: How far the detected quad's aspect ratio may stray from a real card before it
#: is rejected. Without a check here a square-ish blob - a coaster, a phone, the
#: edge of the desk - passes as a card, gets dewarped into a card-shaped image,
#: and is then matched against the index, where it lands on something arbitrary.
ASPECT_TOLERANCE = 0.35
#: Tried in order against each candidate contour. A clean outline closes at the
#: tight value; a broken one - low contrast, a shadow across a corner - needs a
#: looser approximation before it collapses to four points.
APPROX_EPSILONS = (0.02, 0.04, 0.08)


@dataclass(frozen=True)
class Detection:
    """A located card: its corners in the original image, and the flat version."""

    corners: np.ndarray  # (4, 2) float32, ordered top-left clockwise
    image: np.ndarray  # dewarped BGR, CARD_HEIGHT x CARD_WIDTH
    area_fraction: float
    #: Which strategy found it. Worth knowing: a card found by the rotated-rect
    #: fallback has squarer corners than one found from a clean quad, and is
    #: likelier to score low downstream.
    method: str = "quad"


def order_corners(points: np.ndarray) -> np.ndarray:
    """Order four points top-left, top-right, bottom-right, bottom-left.

    cv2 returns contour points in arbitrary rotation, so without this the warp
    produces a card that is upside down or mirrored roughly half the time.
    """
    points = points.reshape(4, 2).astype(np.float32)
    ordered = np.zeros((4, 2), dtype=np.float32)

    # The corner sums and differences separate cleanly for any convex quad.
    total = points.sum(axis=1)
    ordered[0] = points[np.argmin(total)]  # top-left has the smallest x+y
    ordered[2] = points[np.argmax(total)]  # bottom-right the largest

    diff = np.diff(points, axis=1).ravel()
    ordered[1] = points[np.argmin(diff)]  # top-right: smallest y-x
    ordered[3] = points[np.argmax(diff)]
    return ordered


def _plausible_aspect(corners: np.ndarray) -> bool:
    """Whether a quad is shaped like a card, either way up.

    Measured from the ordered corners rather than the bounding box, so a tilted
    card is judged on its own edges and not on the box around it.
    """
    ordered = order_corners(corners)
    top = float(np.linalg.norm(ordered[1] - ordered[0]))
    bottom = float(np.linalg.norm(ordered[2] - ordered[3]))
    left = float(np.linalg.norm(ordered[3] - ordered[0]))
    right = float(np.linalg.norm(ordered[2] - ordered[1]))

    width = (top + bottom) / 2
    height = (left + right) / 2
    if width <= 1 or height <= 1:
        return False

    # Accept either orientation: a card photographed on its side is still a card.
    ratio = width / height
    for candidate in (CARD_ASPECT, 1 / CARD_ASPECT):
        if abs(ratio - candidate) / candidate <= ASPECT_TOLERANCE:
            return True
    return False


def _edge_maps(gray: np.ndarray) -> list[np.ndarray]:
    """Several views of the same frame, because one is not enough.

    Canny with fixed thresholds is the obvious approach and it fails on a
    low-contrast scene - a dark card border on a grey desk - where the outline
    comes back broken and never closes into a quad. So the thresholds are also
    derived from the image's own median, and Otsu is run as a third strategy
    that ignores edge strength altogether.
    """
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    kernel = np.ones((3, 3), np.uint8)
    maps = []

    # 1. Fixed thresholds. Fast, and right for a well-lit photo.
    maps.append(cv2.Canny(blurred, 50, 150))

    # 2. Thresholds from the image's own brightness, for anything dimmer.
    median = float(np.median(blurred))
    lower = int(max(0, 0.66 * median))
    upper = int(min(255, 1.33 * median))
    maps.append(cv2.Canny(blurred, lower, max(upper, lower + 1)))

    # 3. Canny again, closed with a large kernel. Dilating by 3x3 does not
    #    bridge a real gap in an outline; a 7x7 close does, and a closed outline
    #    is the difference between four corners and nine.
    big = np.ones((7, 7), np.uint8)
    maps.append(cv2.morphologyEx(maps[0], cv2.MORPH_CLOSE, big, iterations=2))

    # 4. Otsu, which splits the histogram rather than looking for edges. This is
    #    what catches a card whose border barely differs from the surface.
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    maps.append(cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2))
    maps.append(cv2.bitwise_not(binary))

    return [cv2.dilate(edge, kernel, iterations=1) for edge in maps]


def _quad_from_contour(contour: np.ndarray) -> np.ndarray | None:
    """Four corners from a contour, or None.

    Three attempts, in order of how much they assume:

    1. Progressively looser polygon approximations of the contour itself. This
       is the clean case and gives the truest corners.
    2. The same, on the contour's convex hull. An edge map does not return
       filled regions, it returns thin curves, and a card border crossed by a
       shadow or a weak-contrast patch comes back as an open C-shape that never
       approximates to four points. A card is convex, so the hull of a broken
       card outline is still the card.
    3. The minimum-area rotated rectangle, for a card with a corner lost
       entirely.

    Each candidate must look like a card and must actually account for the shape
    it came from, so a stray C never passes as a rectangle.
    """
    for candidate in (contour, cv2.convexHull(contour)):
        perimeter = cv2.arcLength(candidate, closed=True)
        if perimeter <= 0:
            continue
        for epsilon in APPROX_EPSILONS:
            approx = cv2.approxPolyDP(candidate, epsilon * perimeter, closed=True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                corners = approx.reshape(4, 2).astype(np.float32)
                if _plausible_aspect(corners) and _fills(candidate, corners):
                    return corners

    hull = cv2.convexHull(contour)
    box = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
    if _plausible_aspect(box) and _fills(hull, box):
        return box
    return None


def _fills(shape: np.ndarray, quad: np.ndarray, threshold: float = 0.80) -> bool:
    """Whether a quad actually describes the shape it was derived from.

    Without this a C-shape or an L-shape passes, because its bounding
    quadrilateral is a perfectly respectable rectangle that happens to contain
    almost nothing. The quad is then dewarped and matched against the index,
    where it lands on whichever card is nearest by accident.
    """
    quad_area = abs(cv2.contourArea(quad.reshape(-1, 1, 2).astype(np.float32)))
    if quad_area <= 0:
        return False
    return abs(cv2.contourArea(shape)) >= threshold * quad_area


def _card_contour(gray: np.ndarray) -> tuple[np.ndarray, str] | None:
    """The largest card-shaped quad in the frame, and how it was found."""
    frame_area = gray.shape[0] * gray.shape[1]
    minimum = frame_area * MIN_AREA_FRACTION

    for index, edges in enumerate(_edge_maps(gray)):
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True):
            if cv2.contourArea(contour) < minimum:
                break  # sorted, so everything after is smaller too
            # A card cannot fill the entire frame edge to edge; a contour that
            # does is the frame border, not the card.
            if cv2.contourArea(contour) > frame_area * 0.98:
                continue
            quad = _quad_from_contour(contour)
            if quad is not None:
                return quad, f"strategy-{index}"
    return None


def dewarp(image: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Perspective-correct the quad defined by `corners` to a canonical card."""
    destination = np.array(
        [[0, 0], [CARD_WIDTH - 1, 0],
         [CARD_WIDTH - 1, CARD_HEIGHT - 1], [0, CARD_HEIGHT - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(order_corners(corners), destination)
    return cv2.warpPerspective(image, matrix, (CARD_WIDTH, CARD_HEIGHT))


def detect_card(image: np.ndarray) -> Detection | None:
    """Locate and flatten a single card. None if nothing card-shaped is found.

    Returning None rather than raising: a frame with no card in it is the normal
    case when scanning from a webcam, not an error.
    """
    if image is None or image.size == 0:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    found = _card_contour(gray)
    if found is None:
        return None

    quad, method = found
    corners = order_corners(quad)
    area = abs(cv2.contourArea(corners))
    return Detection(
        corners=corners,
        image=dewarp(image, corners),
        area_fraction=float(area / (gray.shape[0] * gray.shape[1])),
        method=method,
    )


def normalise_scan(image: np.ndarray) -> np.ndarray:
    """Use a whole image as if it were already a flat card.

    For scanner output or a cropped photo, where detection is unnecessary and
    would only risk finding the wrong rectangle.
    """
    return cv2.resize(image, (CARD_WIDTH, CARD_HEIGHT), interpolation=cv2.INTER_AREA)
