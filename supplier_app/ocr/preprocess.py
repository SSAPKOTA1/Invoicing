"""Image clean-up before OCR (grayscale, upscale, denoise, deskew, binarize)."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

MAX_SIDE = 6000
MIN_SIDE = 1600


def to_gray(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("L"))


def estimate_skew(gray: np.ndarray) -> float:
    """Skew angle in degrees (positive = text rotated counter-clockwise), searched in -10..10."""
    small = gray
    if max(gray.shape) > 1600:
        scale = 1600 / max(gray.shape)
        small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _t, binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    best_angle, best_score = 0.0, -1.0
    h, w = binary.shape
    center = (w / 2, h / 2)
    for angle in np.arange(-10.0, 10.01, 0.5):
        m = cv2.getRotationMatrix2D(center, float(angle), 1.0)
        rotated = cv2.warpAffine(binary, m, (w, h), flags=cv2.INTER_NEAREST)
        profile = rotated.sum(axis=1).astype(np.float64)
        score = float(np.var(profile))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def preprocess(image: Image.Image, *, deskew: bool = True) -> Image.Image:
    """Return a cleaned, upright, high-contrast image suitable for Tesseract."""
    gray = to_gray(image)
    h, w = gray.shape
    longest = max(h, w)
    if longest < MIN_SIDE:
        scale = MIN_SIDE / longest
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    elif longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.medianBlur(gray, 3)
    if deskew:
        angle = estimate_skew(gray)
        if abs(angle) >= 0.3:
            hh, ww = gray.shape
            m = cv2.getRotationMatrix2D((ww / 2, hh / 2), angle, 1.0)
            gray = cv2.warpAffine(gray, m, (ww, hh), flags=cv2.INTER_CUBIC, borderValue=255)
    # flatten uneven illumination, then Otsu
    background = cv2.medianBlur(cv2.dilate(gray, np.ones((15, 15), np.uint8)), 21)
    flat = cv2.divide(gray, background, scale=255)
    _t, binary = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    return Image.fromarray(binary)
