#!/usr/bin/env python3
"""
deai.py — Remove AI-generated image artifacts to make images look like real photos.

Processes three layers:
  1. Pixel: sensor noise, variable sharpness, frequency domain cleanup
  2. Metadata: EXIF injection, color space, JPEG quantization tables
  3. Optical: chromatic aberration, lens vignetting, micro lens distortion

Usage:
  python3 deai.py input.png -o output.jpg
  python3 deai.py input.png --preset heavy --camera iphone15
  python3 deai.py input.png --preset light --camera canon_r5
"""

import argparse
import io
import json
import os

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}
import struct
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
import random

import numpy as np
from PIL import Image, ImageFilter, ImageDraw

# Optional imports
try:
    import piexif
    HAS_PIEXIF = True
except ImportError:
    HAS_PIEXIF = False

try:
    from scipy import ndimage
    from scipy.fft import fft2, ifft2, fftshift
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Camera profiles: quantization tables + EXIF templates
# ---------------------------------------------------------------------------

CAMERA_PROFILES = {
    "iphone15": {
        "make": "Apple",
        "model": "iPhone 15 Pro Max",
        "software": "17.4.1",
        "focal_length": (6900, 1000),   # 6.9mm = 24mm equiv
        "focal_length_35mm": 24,
        "f_number": (1780, 1000),       # f/1.78
        "iso": (64, 800),
        "exposure_time_range": ((1, 8000), (1, 30)),
        "color_space": 65535,           # Uncalibrated (Display P3)
        "lens_make": "Apple",
        "lens_model": "iPhone 15 Pro Max back triple camera 6.765mm f/1.78",
        # iPhone JPEG quantization tables (approximation of typical iPhone output)
        "qt_luma": [
            2,  1,  1,  2,  3,  5,  6,  7,
            1,  1,  2,  2,  3,  7,  7,  7,
            2,  2,  2,  3,  5,  7,  8,  7,
            2,  2,  3,  3,  6, 10,  9,  7,
            2,  3,  4,  7,  8, 13, 12,  9,
            3,  4,  6,  7, 10, 12, 14, 11,
            6,  7,  9, 10, 12, 15, 14, 12,
            8, 11, 11, 12, 13, 12, 12, 12,
        ],
        "qt_chroma": [
            2,  2,  3,  6, 12, 12, 12, 12,
            2,  3,  3,  8, 12, 12, 12, 12,
            3,  3,  7, 12, 12, 12, 12, 12,
            6,  8, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
        ],
    },
    "canon_r5": {
        "make": "Canon",
        "model": "Canon EOS R5",
        "software": "Firmware Version 1.8.1",
        "focal_length": (50000, 1000),
        "focal_length_35mm": 50,
        "f_number": (1400, 1000),       # f/1.4
        "iso": (100, 6400),
        "exposure_time_range": ((1, 8000), (1, 15)),
        "color_space": 2,               # Adobe RGB
        "lens_make": "Canon",
        "lens_model": "RF50mm F1.2 L USM",
        "qt_luma": [
            1,  1,  1,  2,  3,  5,  6,  7,
            1,  1,  1,  2,  3,  7,  7,  6,
            1,  1,  2,  3,  5,  7,  8,  6,
            1,  2,  2,  3,  6, 10, 10,  7,
            2,  2,  4,  6,  8, 13, 12,  9,
            3,  4,  5,  7, 10, 12, 14, 11,
            5,  7,  8, 10, 12, 15, 15, 12,
            7, 10, 11, 11, 13, 12, 12, 12,
        ],
        "qt_chroma": [
            1,  1,  2,  5, 12, 12, 12, 12,
            1,  2,  2,  7, 12, 12, 12, 12,
            2,  2,  5, 12, 12, 12, 12, 12,
            5,  7, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
        ],
    },
    "sony_a7iv": {
        "make": "SONY",
        "model": "ILCE-7M4",
        "software": "ILCE-7M4 v2.01",
        "focal_length": (35000, 1000),
        "focal_length_35mm": 35,
        "f_number": (1800, 1000),
        "iso": (100, 12800),
        "exposure_time_range": ((1, 8000), (1, 15)),
        "color_space": 1,               # sRGB
        "lens_make": "SONY",
        "lens_model": "FE 35mm F1.8",
        "qt_luma": [
            1,  1,  1,  2,  3,  5,  6,  7,
            1,  1,  2,  2,  3,  7,  7,  7,
            1,  2,  2,  3,  5,  7,  8,  7,
            2,  2,  3,  3,  6, 10,  9,  7,
            2,  3,  4,  7,  8, 13, 12,  9,
            3,  4,  6,  7, 10, 12, 14, 11,
            6,  7,  9, 10, 12, 15, 14, 12,
            8, 11, 11, 12, 13, 12, 12, 12,
        ],
        "qt_chroma": [
            2,  2,  3,  6, 12, 12, 12, 12,
            2,  2,  3,  8, 12, 12, 12, 12,
            3,  3,  7, 12, 12, 12, 12, 12,
            6,  8, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
        ],
    },
    "nikon_z8": {
        "make": "NIKON CORPORATION",
        "model": "NIKON Z 8",
        "software": "Ver.02.01",
        "focal_length": (85000, 1000),
        "focal_length_35mm": 85,
        "f_number": (1400, 1000),
        "iso": (64, 6400),
        "exposure_time_range": ((1, 8000), (1, 15)),
        "color_space": 1,
        "lens_make": "NIKON",
        "lens_model": "NIKKOR Z 85mm f/1.8 S",
        "qt_luma": [
            2,  1,  1,  2,  3,  5,  6,  7,
            1,  1,  1,  2,  3,  7,  7,  7,
            1,  1,  2,  3,  5,  7,  8,  7,
            2,  2,  2,  3,  6, 10,  9,  7,
            2,  3,  4,  6,  8, 13, 12,  9,
            3,  4,  6,  7, 10, 12, 14, 11,
            5,  7,  9, 10, 12, 15, 14, 12,
            8, 11, 11, 12, 13, 12, 12, 12,
        ],
        "qt_chroma": [
            2,  2,  3,  6, 12, 12, 12, 12,
            2,  2,  3,  7, 12, 12, 12, 12,
            3,  3,  6, 12, 12, 12, 12, 12,
            6,  7, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
            12, 12, 12, 12, 12, 12, 12, 12,
        ],
    },
}

# ---------------------------------------------------------------------------
# Preset configurations
# ---------------------------------------------------------------------------

PRESETS = {
    # --- Photo mode presets (simulates real camera) ---
    "light": {
        "mode": "photo",
        "noise_intensity": 0.008,
        "noise_color_ratio": 0.3,
        "variable_blur_strength": 0.3,
        "chromatic_aberration": 0.3,
        "vignette_strength": 0.08,
        "fft_perturbation": 0.15,
        "micro_distortion": 0.2,
        "jpeg_quality": 95,
        "hot_pixel_count": 2,
        "banding_strength": 0.0,
        "paper_texture": 0.0,
        "gradient_break": 0.0,
        "micro_jitter": 0.0,
        "invisible_wm_disrupt": 0.3,
        "color_correction": 0.2,
        "double_compression": True,
    },
    "medium": {
        "mode": "photo",
        "noise_intensity": 0.015,
        "noise_color_ratio": 0.4,
        "variable_blur_strength": 0.6,
        "chromatic_aberration": 0.6,
        "vignette_strength": 0.15,
        "fft_perturbation": 0.3,
        "micro_distortion": 0.4,
        "jpeg_quality": 92,
        "hot_pixel_count": 5,
        "banding_strength": 0.01,
        "paper_texture": 0.0,
        "gradient_break": 0.0,
        "micro_jitter": 0.0,
        "invisible_wm_disrupt": 0.5,
        "color_correction": 0.4,
        "double_compression": True,
    },
    "heavy": {
        "mode": "photo",
        "noise_intensity": 0.025,
        "noise_color_ratio": 0.5,
        "variable_blur_strength": 1.0,
        "chromatic_aberration": 1.0,
        "vignette_strength": 0.25,
        "fft_perturbation": 0.5,
        "micro_distortion": 0.7,
        "jpeg_quality": 88,
        "hot_pixel_count": 12,
        "banding_strength": 0.02,
        "paper_texture": 0.0,
        "gradient_break": 0.0,
        "micro_jitter": 0.0,
        "invisible_wm_disrupt": 0.7,
        "color_correction": 0.6,
        "double_compression": True,
    },
    # --- Illustration mode presets (for cartoons, illustrations, AI text images) ---
    "illust-light": {
        "mode": "illustration",
        "noise_intensity": 0.004,
        "noise_color_ratio": 0.15,
        "variable_blur_strength": 0.0,
        "chromatic_aberration": 0.0,
        "vignette_strength": 0.0,
        "fft_perturbation": 0.1,
        "micro_distortion": 0.0,
        "jpeg_quality": 94,
        "hot_pixel_count": 0,
        "banding_strength": 0.0,
        "paper_texture": 0.3,
        "gradient_break": 0.2,
        "micro_jitter": 0.2,
        "invisible_wm_disrupt": 0.3,
        "color_correction": 0.2,
        "double_compression": False,
    },
    "illust-medium": {
        "mode": "illustration",
        "noise_intensity": 0.004,
        "noise_color_ratio": 0.15,
        "variable_blur_strength": 0.0,
        "chromatic_aberration": 0.0,
        "vignette_strength": 0.0,
        "fft_perturbation": 0.15,
        "micro_distortion": 0.0,
        "jpeg_quality": 92,
        "hot_pixel_count": 0,
        "banding_strength": 0.0,
        "paper_texture": 0.3,
        "gradient_break": 0.25,
        "micro_jitter": 0.25,
        "invisible_wm_disrupt": 0.5,
        "color_correction": 0.4,
        "double_compression": True,
    },
    "illust-heavy": {
        "mode": "illustration",
        "noise_intensity": 0.01,
        "noise_color_ratio": 0.25,
        "variable_blur_strength": 0.0,
        "chromatic_aberration": 0.0,
        "vignette_strength": 0.0,
        "fft_perturbation": 0.3,
        "micro_distortion": 0.0,
        "jpeg_quality": 88,
        "hot_pixel_count": 0,
        "banding_strength": 0.0,
        "paper_texture": 0.8,
        "gradient_break": 0.6,
        "micro_jitter": 0.6,
        "invisible_wm_disrupt": 0.7,
        "color_correction": 0.6,
        "double_compression": True,
    },
}


# ---------------------------------------------------------------------------
# Processing functions
# ---------------------------------------------------------------------------

def add_sensor_noise(img_array: np.ndarray, intensity: float, color_ratio: float) -> np.ndarray:
    """
    Add realistic sensor noise that varies with pixel brightness.
    Real sensors: dark areas have more visible noise (Poisson + read noise),
    bright areas have shot noise proportional to sqrt(signal).
    """
    h, w, c = img_array.shape
    img_float = img_array.astype(np.float64) / 255.0

    # Luminance map for intensity-dependent noise
    luma = 0.299 * img_float[:,:,0] + 0.587 * img_float[:,:,1] + 0.114 * img_float[:,:,2]

    # Noise is stronger in darker areas (inverse relationship)
    noise_map = intensity * (1.0 + 1.5 * (1.0 - luma))

    # Luminance noise (all channels)
    luma_noise = np.random.normal(0, 1, (h, w))

    # Chroma noise (per-channel, slightly different)
    chroma_noise = np.random.normal(0, 1, (h, w, c))

    for ch in range(c):
        channel_noise = (1.0 - color_ratio) * luma_noise + color_ratio * chroma_noise[:,:,ch]
        img_float[:,:,ch] += channel_noise * noise_map

    # Add very subtle Poisson-like shot noise in bright areas
    bright_mask = luma > 0.6
    if np.any(bright_mask):
        shot_noise = np.random.normal(0, intensity * 0.3, (h, w))
        shot_noise *= bright_mask.astype(np.float64)
        for ch in range(c):
            img_float[:,:,ch] += shot_noise

    return np.clip(img_float * 255.0, 0, 255).astype(np.uint8)


def add_hot_pixels(img_array: np.ndarray, count: int) -> np.ndarray:
    """Add a few hot/stuck pixels — common in real sensors."""
    h, w, _ = img_array.shape
    result = img_array.copy()
    for _ in range(count):
        y, x = random.randint(0, h-1), random.randint(0, w-1)
        ch = random.randint(0, 2)
        # Hot pixels are usually stuck at max in one channel
        result[y, x, ch] = min(255, int(result[y, x, ch]) + random.randint(180, 255))
    return result


def add_banding(img_array: np.ndarray, strength: float) -> np.ndarray:
    """Add subtle horizontal banding noise (sensor readout artifact)."""
    if strength <= 0:
        return img_array
    h, w, c = img_array.shape
    # Generate per-row offset
    row_offsets = np.random.normal(0, strength * 255, h).astype(np.float64)
    # Smooth it slightly so it's not pure random
    kernel_size = max(3, h // 100)
    if kernel_size % 2 == 0:
        kernel_size += 1
    row_offsets = np.convolve(row_offsets, np.ones(kernel_size)/kernel_size, mode='same')

    result = img_array.astype(np.float64)
    for i in range(h):
        result[i, :, :] += row_offsets[i]

    return np.clip(result, 0, 255).astype(np.uint8)


def apply_variable_blur(img: Image.Image, strength: float) -> Image.Image:
    """
    Simulate depth-of-field: sharp center region, progressively blurred edges.
    Real photos have non-uniform sharpness due to lens optics.
    """
    if strength <= 0:
        return img

    w, h = img.size

    # Create a radial gradient mask (center = sharp, edges = blurry)
    cx, cy = w // 2 + random.randint(-w//8, w//8), h // 2 + random.randint(-h//8, h//8)
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    max_dist = np.sqrt(cx**2 + cy**2)
    dist_norm = np.clip(dist / max_dist, 0, 1)

    # Create multiple blur levels
    blur_levels = [
        img,
        img.filter(ImageFilter.GaussianBlur(radius=0.5 * strength)),
        img.filter(ImageFilter.GaussianBlur(radius=1.2 * strength)),
        img.filter(ImageFilter.GaussianBlur(radius=2.0 * strength)),
    ]

    result = np.array(img).astype(np.float64)
    blur_arrays = [np.array(b).astype(np.float64) for b in blur_levels]

    # Blend based on distance from focus point
    for y in range(h):
        for x in range(w):
            d = dist_norm[y, x]
            if d < 0.3:
                # Sharp zone - no blur
                pass
            elif d < 0.5:
                t = (d - 0.3) / 0.2
                result[y, x] = (1 - t) * blur_arrays[0][y, x] + t * blur_arrays[1][y, x]
            elif d < 0.7:
                t = (d - 0.5) / 0.2
                result[y, x] = (1 - t) * blur_arrays[1][y, x] + t * blur_arrays[2][y, x]
            else:
                t = min(1.0, (d - 0.7) / 0.3)
                result[y, x] = (1 - t) * blur_arrays[2][y, x] + t * blur_arrays[3][y, x]

    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def apply_variable_blur_fast(img: Image.Image, strength: float) -> Image.Image:
    """
    Fast version using scipy for large images.
    Uses mask-based alpha blending instead of per-pixel loop.
    """
    if strength <= 0 or not HAS_SCIPY:
        return apply_variable_blur(img, strength)

    w, h = img.size
    cx = w // 2 + random.randint(-w//8, w//8)
    cy = h // 2 + random.randint(-h//8, h//8)

    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
    max_dist = np.sqrt(max(cx, w-cx)**2 + max(cy, h-cy)**2)
    dist_norm = np.clip(dist / max_dist, 0, 1)

    img_array = np.array(img).astype(np.float64)

    # Create blur levels using scipy
    blur_sigmas = [0, 0.5 * strength, 1.2 * strength, 2.5 * strength]
    blurred = []
    for sigma in blur_sigmas:
        if sigma == 0:
            blurred.append(img_array.copy())
        else:
            blurred.append(ndimage.gaussian_filter(img_array, sigma=[sigma, sigma, 0]))

    # Create smooth transition masks
    result = blurred[0].copy()

    # Zone 1: 0.3-0.5 → blend level 0 and 1
    mask1 = np.clip((dist_norm - 0.3) / 0.2, 0, 1)[:,:,np.newaxis]
    result = result * (1 - mask1) + blurred[1] * mask1

    # Zone 2: 0.5-0.7 → blend towards level 2
    mask2 = np.clip((dist_norm - 0.5) / 0.2, 0, 1)[:,:,np.newaxis]
    result = result * (1 - mask2) + blurred[2] * mask2

    # Zone 3: 0.7-1.0 → blend towards level 3
    mask3 = np.clip((dist_norm - 0.7) / 0.3, 0, 1)[:,:,np.newaxis]
    result = result * (1 - mask3) + blurred[3] * mask3

    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8))


def perturb_frequency_domain(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    Break up the unnaturally uniform high-frequency patterns that diffusion models produce.

    Key insight: AI detection measures CV (std/mean) of log-magnitude in the high-freq band.
    Random noise doesn't change CV because of the law of large numbers.
    We need STRUCTURED, large-scale modulation that creates genuine regions of high vs low
    energy — mimicking a real lens MTF (Modulation Transfer Function):
      - Real lenses have directional asymmetry (astigmatism)
      - MTF falls off faster in corners than center
      - Different channels have slightly different MTF curves (lateral CA)
    """
    if not HAS_SCIPY or strength <= 0:
        return img_array

    result = img_array.astype(np.float64)
    h, w = img_array.shape[:2]
    cy, cx = h // 2, w // 2

    # Pre-compute frequency space coordinates once
    Y_full, X_full = np.mgrid[:h, :w]
    dist = np.sqrt((X_full - cx)**2 + (Y_full - cy)**2)
    max_dist = np.sqrt(cx**2 + cy**2)
    freq_norm = dist / max_dist
    angle_map = np.arctan2(Y_full - cy, X_full - cx)

    high_freq_mask = freq_norm > 0.3

    for ch in range(3):
        channel = result[:,:,ch]
        F = fft2(channel)
        F_shifted = fftshift(F)
        magnitude = np.abs(F_shifted)
        phase = np.angle(F_shifted)

        # === MTF simulation: directional asymmetry ===
        # Real lenses resolve more in one axis than the other (astigmatism)
        # Create an elliptical MTF that attenuates more in one direction
        astig_angle = np.random.uniform(0, np.pi)  # random orientation per channel
        astig_strength = 0.15 + strength * 0.25  # how elliptical
        cos_a = np.cos(angle_map - astig_angle)
        sin_a = np.sin(angle_map - astig_angle)
        # Effective frequency with direction-dependent scaling
        eff_freq = freq_norm * (1.0 + astig_strength * cos_a**2)

        # MTF curve: smooth rolloff that's direction-dependent
        # Real MTF ≈ 1 at low freq, drops to near 0 at Nyquist
        mtf_cutoff = 0.6 + np.random.uniform(-0.1, 0.1)  # slightly different per channel
        mtf = np.exp(-((eff_freq / mtf_cutoff) ** 2) * strength * 2)
        # Only apply in high-freq region, leave low/mid alone
        mtf[~high_freq_mask] = 1.0

        # === Sector-based energy modulation ===
        # CV = std/mean. Current CV ≈ 0.09, need > 0.5.
        # Must create 5x more variance. Use aggressive lognormal scaling per sector.
        n_sectors = np.random.randint(4, 8)
        # lognormal with sigma=1.2*strength gives wide spread (e.g. 0.2x to 5x)
        sector_scales = np.random.lognormal(0, 1.2 + strength * 0.8, n_sectors)
        sector_idx = ((angle_map + np.pi) / (2 * np.pi) * n_sectors).astype(int) % n_sectors
        sector_map = sector_scales[sector_idx]
        sector_map[~high_freq_mask] = 1.0

        # === Radial rings of varying energy ===
        n_rings = np.random.randint(3, 7)
        ring_phase = np.random.uniform(0, 2 * np.pi)
        ring_modulation = 1.0 + strength * 0.8 * np.sin(freq_norm * n_rings * np.pi * 2 + ring_phase)
        ring_modulation[~high_freq_mask] = 1.0

        # === Combine all magnitude modulations ===
        combined_mod = mtf * sector_map * ring_modulation
        combined_mod *= np.random.normal(1.0, strength * 0.15, (h, w))
        combined_mod[~high_freq_mask] = 1.0

        new_magnitude = magnitude * combined_mod

        # === Phase perturbation (less important for CV, but adds naturalness) ===
        phase_noise = np.random.normal(0, strength * 0.5, (h, w))
        phase_noise[~high_freq_mask] = 0
        new_phase = phase + phase_noise

        F_perturbed = new_magnitude * np.exp(1j * new_phase)
        F_back = fftshift(F_perturbed)
        channel_back = np.real(ifft2(F_back))

        result[:,:,ch] = channel_back

    return np.clip(result, 0, 255).astype(np.uint8)


def add_chromatic_aberration(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    Simulate lateral chromatic aberration: slight color fringing at edges.
    Real lenses shift R and B channels slightly relative to G at image periphery.
    """
    if strength <= 0:
        return img_array

    h, w, _ = img_array.shape
    cx, cy = w / 2, h / 2

    # Shift amount increases with distance from center
    max_shift = strength * 1.5  # pixels at the very edge

    result = img_array.copy()

    # Red channel: shift outward slightly
    Y, X = np.mgrid[:h, :w].astype(np.float64)
    dx_r = (X - cx) / max(cx, 1) * max_shift
    dy_r = (Y - cy) / max(cy, 1) * max_shift

    if HAS_SCIPY:
        result[:,:,0] = ndimage.map_coordinates(
            img_array[:,:,0],
            [Y - dy_r * 0.5, X - dx_r * 0.5],
            order=1, mode='reflect'
        )
        result[:,:,2] = ndimage.map_coordinates(
            img_array[:,:,2],
            [Y + dy_r * 0.5, X + dx_r * 0.5],
            order=1, mode='reflect'
        )
    else:
        # Simple integer-shift fallback
        shift = max(1, int(max_shift))
        # Shift red right/down, blue left/up at edges
        result[shift:, shift:, 0] = img_array[:-shift, :-shift, 0]
        result[:-shift, :-shift, 2] = img_array[shift:, shift:, 2]

    return result


def add_vignette(img_array: np.ndarray, strength: float) -> np.ndarray:
    """Add lens vignetting — darker corners, brighter center."""
    if strength <= 0:
        return img_array

    h, w, _ = img_array.shape
    # Slightly off-center to look natural
    cx = w / 2 + random.randint(-w//20, w//20)
    cy = h / 2 + random.randint(-h//20, h//20)

    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt(((X - cx) / (w/2))**2 + ((Y - cy) / (h/2))**2)

    # Vignette falloff: cos^4 approximation (physically-based)
    vignette = np.clip(1.0 - strength * dist**2, 0, 1)

    result = img_array.astype(np.float64)
    for ch in range(3):
        result[:,:,ch] *= vignette

    return np.clip(result, 0, 255).astype(np.uint8)


def add_micro_distortion(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    Add subtle barrel/pincushion distortion that real lenses have.
    Also adds very slight local waviness (lens element imperfections).
    """
    if strength <= 0 or not HAS_SCIPY:
        return img_array

    h, w, _ = img_array.shape
    cx, cy = w / 2, h / 2

    Y, X = np.mgrid[:h, :w].astype(np.float64)
    dx = (X - cx) / max(cx, 1)
    dy = (Y - cy) / max(cy, 1)
    r2 = dx**2 + dy**2

    # Barrel distortion coefficient (very subtle)
    k1 = -0.02 * strength
    k2 = 0.005 * strength

    # Distortion mapping
    r_distorted = 1 + k1 * r2 + k2 * r2**2
    new_x = cx + dx * max(cx, 1) * r_distorted
    new_y = cy + dy * max(cy, 1) * r_distorted

    # Add micro waviness
    wave_freq = 0.01 * strength
    wave_amp = 0.5 * strength
    new_x += wave_amp * np.sin(Y * wave_freq * 2 * np.pi / h)
    new_y += wave_amp * np.cos(X * wave_freq * 2 * np.pi / w)

    result = img_array.copy()
    for ch in range(3):
        result[:,:,ch] = ndimage.map_coordinates(
            img_array[:,:,ch],
            [new_y, new_x],
            order=1, mode='reflect'
        )

    return result


def generate_exif(camera_profile: dict) -> bytes:
    """Generate realistic EXIF data for the chosen camera profile."""
    if not HAS_PIEXIF:
        return b""

    # Random but realistic timestamp (within last 30 days)
    now = datetime.now()
    offset = random.randint(0, 30 * 24 * 3600)
    shot_time = now - timedelta(seconds=offset)
    time_str = shot_time.strftime("%Y:%m:%d %H:%M:%S")

    # Random ISO within camera's range
    iso_min, iso_max = camera_profile["iso"]
    # Weighted towards lower ISOs (more common in practice)
    iso = random.choice([
        iso_min,
        iso_min * 2,
        iso_min * 4,
        random.randint(iso_min, iso_max),
    ])

    # Random exposure time
    exp_fast, exp_slow = camera_profile["exposure_time_range"]
    exp_denom = random.randint(exp_fast[1] // 4, exp_fast[1])
    exposure_time = (1, max(1, exp_denom))

    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: camera_profile["make"].encode(),
            piexif.ImageIFD.Model: camera_profile["model"].encode(),
            piexif.ImageIFD.Software: camera_profile["software"].encode(),
            piexif.ImageIFD.DateTime: time_str.encode(),
            piexif.ImageIFD.Orientation: 1,
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: time_str.encode(),
            piexif.ExifIFD.DateTimeDigitized: time_str.encode(),
            piexif.ExifIFD.ExposureTime: exposure_time,
            piexif.ExifIFD.FNumber: camera_profile["f_number"],
            piexif.ExifIFD.ISOSpeedRatings: iso,
            piexif.ExifIFD.FocalLength: camera_profile["focal_length"],
            piexif.ExifIFD.FocalLengthIn35mmFilm: camera_profile["focal_length_35mm"],
            piexif.ExifIFD.ColorSpace: camera_profile["color_space"],
            piexif.ExifIFD.ExposureProgram: 2,     # Normal program
            piexif.ExifIFD.MeteringMode: 5,        # Pattern
            piexif.ExifIFD.Flash: 0,                # No flash
            piexif.ExifIFD.WhiteBalance: 0,         # Auto
            piexif.ExifIFD.ExposureMode: 0,         # Auto
            piexif.ExifIFD.SceneCaptureType: 0,     # Standard
            piexif.ExifIFD.LensMake: camera_profile["lens_make"].encode(),
            piexif.ExifIFD.LensModel: camera_profile["lens_model"].encode(),
        },
    }

    return piexif.dump(exif_dict)


def save_with_quantization_tables(img: Image.Image, output_path: str,
                                   camera_profile: dict, quality: int,
                                   exif_bytes: bytes) -> None:
    """
    Save JPEG with camera-specific quantization tables and EXIF.
    This is the key metadata-level anti-detection: real cameras have unique QT fingerprints.
    """
    qt_luma = camera_profile["qt_luma"]
    qt_chroma = camera_profile["qt_chroma"]

    # PIL's save with qtables parameter
    # qtables format: list of 64-element lists, index 0=luma, 1=chroma
    img.save(
        output_path,
        format="JPEG",
        quality=quality,
        qtables=[qt_luma, qt_chroma],
        exif=exif_bytes if exif_bytes else None,
        subsampling="4:2:0",  # Most common for consumer cameras
    )


# ---------------------------------------------------------------------------
# Illustration-specific processing functions
# ---------------------------------------------------------------------------

def add_paper_texture(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    Add paper/canvas grain texture instead of sensor noise.
    Real hand-drawn or printed illustrations have paper fiber patterns.
    """
    if strength <= 0:
        return img_array

    h, w, c = img_array.shape
    result = img_array.astype(np.float64)

    # Generate multi-scale paper grain
    # Large-scale fiber pattern
    grain_large = np.random.normal(0, 1, (h // 4 + 1, w // 4 + 1))
    if HAS_SCIPY:
        grain_large = ndimage.zoom(grain_large, (h / (h // 4 + 1), w / (w // 4 + 1)))[:h, :w]
        grain_large = ndimage.gaussian_filter(grain_large, sigma=2.0)
    else:
        grain_large = np.array(Image.fromarray(grain_large).resize((w, h), Image.BILINEAR))

    # Fine-scale grain
    grain_fine = np.random.normal(0, 1, (h, w))
    if HAS_SCIPY:
        grain_fine = ndimage.gaussian_filter(grain_fine, sigma=0.5)

    # Combine: 60% large pattern + 40% fine grain
    grain = 0.6 * grain_large + 0.4 * grain_fine

    # Apply uniformly across channels (paper texture affects all colors equally)
    texture_strength = strength * 6.0  # scale to visible range
    for ch in range(c):
        result[:,:,ch] += grain * texture_strength

    return np.clip(result, 0, 255).astype(np.uint8)


def break_gradient_uniformity(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    AI gradients are mathematically perfect. Real artwork has subtle color variation
    within gradient areas — hand tremor, paint mixing, digital brush texture.
    """
    if strength <= 0:
        return img_array

    h, w, c = img_array.shape
    result = img_array.astype(np.float64)

    # Detect gradient regions (areas with small but non-zero local variance)
    if HAS_SCIPY:
        luma = 0.299 * result[:,:,0] + 0.587 * result[:,:,1] + 0.114 * result[:,:,2]
        # Local variance using box filter
        local_mean = ndimage.uniform_filter(luma, size=15)
        local_sq_mean = ndimage.uniform_filter(luma**2, size=15)
        local_var = local_sq_mean - local_mean**2

        # Gradient regions: low variance but not flat (flat = solid fill, leave alone)
        gradient_mask = (local_var > 2) & (local_var < 200)
        gradient_mask = gradient_mask.astype(np.float64)

        # Smooth the mask
        gradient_mask = ndimage.gaussian_filter(gradient_mask, sigma=5.0)
    else:
        # Without scipy, apply everywhere at reduced strength
        gradient_mask = np.ones((h, w)) * 0.5

    # Add color variation in gradient regions
    for ch in range(c):
        # Low-frequency color wobble
        wobble = np.random.normal(0, strength * 3.0, (h // 8 + 1, w // 8 + 1))
        if HAS_SCIPY:
            wobble = ndimage.zoom(wobble, (h / (h // 8 + 1), w / (w // 8 + 1)))[:h, :w]
            wobble = ndimage.gaussian_filter(wobble, sigma=4.0)
        else:
            wobble = np.array(Image.fromarray(wobble).resize((w, h), Image.BILINEAR))

        result[:,:,ch] += wobble * gradient_mask

    return np.clip(result, 0, 255).astype(np.uint8)


def add_micro_jitter(img_array: np.ndarray, strength: float) -> np.ndarray:
    """
    Add sub-pixel jitter that simulates hand-drawing imperfection or
    screen-capture artifacts. Edges in AI art are too mathematically clean.
    """
    if strength <= 0 or not HAS_SCIPY:
        return img_array

    h, w, _ = img_array.shape

    # Very small random displacement field
    jitter_amp = strength * 0.8
    dx = np.random.normal(0, jitter_amp, (h, w))
    dy = np.random.normal(0, jitter_amp, (h, w))

    # Smooth the displacement to make it spatially coherent
    dx = ndimage.gaussian_filter(dx, sigma=3.0)
    dy = ndimage.gaussian_filter(dy, sigma=3.0)

    Y, X = np.mgrid[:h, :w].astype(np.float64)
    new_x = X + dx
    new_y = Y + dy

    result = img_array.copy()
    for ch in range(3):
        result[:,:,ch] = ndimage.map_coordinates(
            img_array[:,:,ch],
            [new_y, new_x],
            order=1, mode='reflect'
        )

    return result


def remove_watermark_region(img: Image.Image, region: str = "auto",
                            margin: int = 5) -> Image.Image:
    """
    Cover watermark region using surrounding pixels (inpainting-lite).
    region: "auto" tries to detect common AI watermark positions,
            or "BR" (bottom-right), "BL", "TR", "TL", or "x,y,w,h" for manual.
    """
    w, h = img.size
    img_array = np.array(img)

    # Determine watermark bounding box
    if region == "auto":
        # Scan common watermark positions: bottom-right and bottom-left corners
        # Most AI tools put watermarks in bottom-right
        boxes = _detect_watermark_candidates(img_array)
        if not boxes:
            return img  # No watermark detected
    elif region in ("BR", "br"):
        # Bottom-right 15% x 8%
        bw, bh = max(30, int(w * 0.15)), max(20, int(h * 0.08))
        boxes = [(w - bw - margin, h - bh - margin, bw, bh)]
    elif region in ("BL", "bl"):
        bw, bh = max(30, int(w * 0.15)), max(20, int(h * 0.08))
        boxes = [(margin, h - bh - margin, bw, bh)]
    elif region in ("TR", "tr"):
        bw, bh = max(30, int(w * 0.15)), max(20, int(h * 0.08))
        boxes = [(w - bw - margin, margin, bw, bh)]
    elif region in ("TL", "tl"):
        bw, bh = max(30, int(w * 0.15)), max(20, int(h * 0.08))
        boxes = [(margin, margin, bw, bh)]
    else:
        # Manual: "x,y,w,h"
        parts = [int(p) for p in region.split(",")]
        boxes = [(parts[0], parts[1], parts[2], parts[3])]

    for (bx, by, bw, bh) in boxes:
        # Expand slightly for better blending
        bx = max(0, bx - margin)
        by = max(0, by - margin)
        bw = min(w - bx, bw + 2 * margin)
        bh = min(h - by, bh + 2 * margin)

        # Sample surrounding pixels for infill
        # Use the strip just above the watermark region
        sample_y_start = max(0, by - bh)
        sample_y_end = by
        if sample_y_end <= sample_y_start:
            sample_y_start = max(0, by - 20)
            sample_y_end = by

        if sample_y_end > sample_y_start:
            sample_strip = img_array[sample_y_start:sample_y_end, bx:bx+bw]
            if sample_strip.size > 0:
                # Tile the sample strip to fill the watermark region
                fill = np.tile(sample_strip, (bh // max(1, sample_strip.shape[0]) + 1, 1, 1))[:bh, :bw]

                # Add slight noise to avoid obvious tiling
                noise = np.random.normal(0, 2.0, fill.shape)
                fill = np.clip(fill.astype(np.float64) + noise, 0, 255).astype(np.uint8)

                # Blend edges with a gradient mask for smooth transition
                blend_mask = np.ones((bh, bw), dtype=np.float64)
                fade = min(10, bh // 3, bw // 3)
                for i in range(fade):
                    t = i / fade
                    blend_mask[i, :] *= t          # top fade
                    blend_mask[-(i+1), :] *= t     # bottom fade
                    blend_mask[:, i] *= t          # left fade
                    blend_mask[:, -(i+1)] *= t     # right fade

                for ch in range(3):
                    orig = img_array[by:by+bh, bx:bx+bw, ch].astype(np.float64)
                    new = fill[:,:,ch].astype(np.float64)
                    img_array[by:by+bh, bx:bx+bw, ch] = (
                        orig * (1 - blend_mask) + new * blend_mask
                    ).astype(np.uint8)

    return Image.fromarray(img_array)


def _detect_watermark_candidates(img_array: np.ndarray) -> list:
    """
    Heuristic detection of watermark regions.
    Looks for small text-like high-contrast patches in corners.
    """
    h, w, _ = img_array.shape
    candidates = []

    # Check each corner region
    corner_h = max(20, int(h * 0.12))
    corner_w = max(40, int(w * 0.20))

    corners = {
        "BR": (w - corner_w, h - corner_h),
        "BL": (0, h - corner_h),
        "TR": (w - corner_w, 0),
        "TL": (0, 0),
    }

    for name, (cx, cy) in corners.items():
        patch = img_array[cy:cy+corner_h, cx:cx+corner_w]
        # Convert to grayscale
        gray = 0.299 * patch[:,:,0] + 0.587 * patch[:,:,1] + 0.114 * patch[:,:,2]

        # Look for high local contrast (text-like features)
        if HAS_SCIPY:
            edges = ndimage.sobel(gray)
            edge_density = np.mean(edges > 30)
        else:
            # Simple gradient approximation
            dx = np.abs(np.diff(gray, axis=1))
            dy = np.abs(np.diff(gray, axis=0))
            edge_density = (np.mean(dx > 15) + np.mean(dy > 15)) / 2

        # Watermark typically has moderate edge density (text edges)
        # but not too high (that would be actual image content)
        if 0.02 < edge_density < 0.25:
            candidates.append((cx, cy, corner_w, corner_h))

    return candidates


# ---------------------------------------------------------------------------
# Scan / Analysis module
# ---------------------------------------------------------------------------

def scan_image(input_path: str, verbose: bool = True) -> dict:
    """
    Analyze an image for AI-generation indicators.
    Returns a report with risk scores per category.
    """
    img = Image.open(input_path).convert("RGB")
    img_array = np.array(img)
    h, w, _ = img_array.shape

    report = {
        "file": input_path,
        "size": f"{w}x{h}",
        "checks": {},
        "risk_level": "LOW",
        "risk_score": 0,
    }

    total_score = 0
    max_score = 0

    def check(name, score, max_s, detail):
        nonlocal total_score, max_score
        total_score += score
        max_score += max_s
        report["checks"][name] = {
            "score": score,
            "max": max_s,
            "detail": detail,
            "risk": "HIGH" if score >= max_s * 0.7 else ("MEDIUM" if score >= max_s * 0.3 else "LOW"),
        }
        if verbose:
            icon = "!!" if score >= max_s * 0.7 else ("! " if score >= max_s * 0.3 else "OK")
            print(f"  [{icon}] {name}: {score}/{max_s} — {detail}")

    if verbose:
        print(f"Scanning: {input_path} ({w}x{h})")
        print("-" * 50)

    # 1. EXIF check
    exif_score = 0
    try:
        if HAS_PIEXIF:
            exif = piexif.load(input_path)
            has_make = bool(exif.get("0th", {}).get(piexif.ImageIFD.Make))
            has_model = bool(exif.get("0th", {}).get(piexif.ImageIFD.Model))
            has_datetime = bool(exif.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal))
            has_focal = bool(exif.get("Exif", {}).get(piexif.ExifIFD.FocalLength))
            missing = []
            if not has_make: missing.append("Make"); exif_score += 5
            if not has_model: missing.append("Model"); exif_score += 5
            if not has_datetime: missing.append("DateTime"); exif_score += 3
            if not has_focal: missing.append("FocalLength"); exif_score += 2
            detail = f"Missing: {', '.join(missing)}" if missing else "Complete"
        else:
            # Check with PIL
            from PIL.ExifTags import Base as ExifBase
            pil_exif = img.getexif()
            if not pil_exif:
                exif_score = 15
                detail = "No EXIF data at all"
            else:
                detail = f"{len(pil_exif)} tags present"
    except Exception:
        exif_score = 15
        detail = "No EXIF data"
    # EXIF penalty cap: JPEG images often have EXIF stripped by social media platforms.
    # A missing EXIF on a JPEG is weak evidence (could be platform re-upload), so cap at 8.
    # Only PNG/WebP with no EXIF gets the full penalty (AI tools output these natively).
    ext = os.path.splitext(input_path)[1].lower()
    if ext in ('.jpg', '.jpeg') and exif_score > 8:
        exif_score = 8
        detail += " (JPEG — 可能被平台剥离EXIF,降低权重)"
    check("EXIF 元数据", exif_score, 15, detail)

    # 2. Noise uniformity
    luma = 0.299 * img_array[:,:,0].astype(float) + 0.587 * img_array[:,:,1].astype(float) + 0.114 * img_array[:,:,2].astype(float)
    # Split into dark/bright regions and compare noise levels
    dark_mask = luma < 80
    bright_mask = luma > 180
    if np.any(dark_mask) and np.any(bright_mask):
        dark_std = np.std(luma[dark_mask])
        bright_std = np.std(luma[bright_mask])
        # Real photos: dark areas have MORE noise (higher std relative to mean)
        # AI images: noise is uniform regardless of brightness
        ratio = bright_std / max(dark_std, 0.01)
        if ratio > 0.8:  # too similar = AI-like
            noise_score = min(15, int((ratio - 0.5) * 20))
            detail = f"暗区std={dark_std:.1f}, 亮区std={bright_std:.1f}, ratio={ratio:.2f} (太均匀)"
        else:
            noise_score = max(0, int((0.8 - ratio) * -5 + 5))
            detail = f"暗区std={dark_std:.1f}, 亮区std={bright_std:.1f}, ratio={ratio:.2f} (正常)"
    else:
        noise_score = 5
        detail = "无法区分明暗区域"
    check("噪点均匀性", noise_score, 15, detail)

    # 3. FFT spectrum analysis
    if HAS_SCIPY:
        gray = luma
        F = np.abs(fftshift(fft2(gray)))
        F_log = np.log1p(F)
        cy, cx = h // 2, w // 2
        Y_full, X_full = np.mgrid[:h, :w]
        dist = np.sqrt((X_full - cx)**2 + (Y_full - cy)**2)
        max_dist = np.sqrt(cx**2 + cy**2)
        freq_norm = dist / max_dist

        # Compare high-freq uniformity vs natural falloff
        high_freq = F_log[freq_norm > 0.5]
        mid_freq = F_log[(freq_norm > 0.2) & (freq_norm < 0.5)]
        high_cv = np.std(high_freq) / max(np.mean(high_freq), 0.01)
        mid_cv = np.std(mid_freq) / max(np.mean(mid_freq), 0.01)

        # Also check directional asymmetry: real lenses have different MTF in X vs Y
        # AI images have near-perfect rotational symmetry
        # Split high-freq into horizontal vs vertical strips
        horiz_mask = (freq_norm > 0.5) & (np.abs(Y_full - cy) < h * 0.1)
        vert_mask = (freq_norm > 0.5) & (np.abs(X_full - cx) < w * 0.1)
        if np.any(horiz_mask) and np.any(vert_mask):
            h_energy = np.mean(F_log[horiz_mask])
            v_energy = np.mean(F_log[vert_mask])
            asymmetry = abs(h_energy - v_energy) / max(h_energy, v_energy, 0.01)
        else:
            asymmetry = 0

        # Scoring: combine CV uniformity + directional symmetry
        # Real photos: CV ~0.06-0.12, but have asymmetry > 0.05
        # AI images: CV ~0.08-0.12, but near-zero asymmetry
        fft_score = 0
        details = []
        # CV check (recalibrated: real photos also have low CV, so lower weight)
        if high_cv < 0.15:
            fft_score += min(8, int((0.15 - high_cv) * 80))
            details.append(f"高频CV={high_cv:.3f}(均匀)")
        # Asymmetry check (more discriminative than CV)
        if asymmetry < 0.03:
            fft_score += min(7, int((0.03 - asymmetry) * 250))
            details.append(f"方向对称={asymmetry:.4f}(太对称)")
        else:
            details.append(f"方向不对称={asymmetry:.4f}")

        detail = ", ".join(details) if details else f"高频CV={high_cv:.3f}, 方向={asymmetry:.4f}"
        if fft_score == 0:
            detail = f"频域正常: CV={high_cv:.3f}, 方向={asymmetry:.4f}"
        check("频域特征", fft_score, 15, detail)
    else:
        check("频域特征", 0, 15, "scipy不可用,跳过")

    # 4. Color histogram shape
    hist_score = 0
    hist_details = []
    for ch, ch_name in enumerate(["R", "G", "B"]):
        hist, _ = np.histogram(img_array[:,:,ch], bins=256, range=(0, 256))
        hist_norm = hist / hist.sum()
        # Real photos rarely have perfectly smooth histograms
        # Calculate histogram smoothness (low-pass filter and compare)
        if HAS_SCIPY:
            smooth = ndimage.gaussian_filter1d(hist_norm.astype(float), sigma=5)
            roughness = np.mean(np.abs(hist_norm - smooth))
            if roughness < 0.00035:
                hist_score += 3
                hist_details.append(f"{ch_name}太光滑({roughness:.5f})")
        # Check for unnatural gaps or spikes
        # Note: real photos after platform re-compression also fill all bins,
        # so this is a very weak signal. Only flag if literally zero empty bins.
        zero_bins = np.sum(hist == 0)
        if zero_bins == 0:
            hist_score += 1  # very weak signal — all 256 bins populated

    detail = "; ".join(hist_details) if hist_details else "色彩分布正常"
    if hist_score == 0:
        detail = "色彩分布正常"
    check("色彩统计分布", hist_score, 12, detail)

    # 5. JPEG compression layers
    jpeg_score = 0
    ext = os.path.splitext(input_path)[1].lower()
    if ext in ('.png', '.webp', '.bmp'):
        jpeg_score = 8
        detail = f"格式={ext} (AI常用, 无JPEG压缩痕迹)"
    elif ext in ('.jpg', '.jpeg'):
        # Check for double compression artifacts
        # Simple heuristic: look at DCT coefficient distribution
        jpeg_score = 2
        detail = "单层JPEG压缩 (可能是AI→JPEG一次保存)"
    else:
        detail = f"格式={ext}"
    check("压缩格式/层数", jpeg_score, 10, detail)

    # 6. Detail uniformity (sharpness variance across regions)
    block_size = min(h, w) // 8
    if block_size > 10 and HAS_SCIPY:
        sharpness_values = []
        for by in range(0, h - block_size, block_size):
            for bx in range(0, w - block_size, block_size):
                block = luma[by:by+block_size, bx:bx+block_size]
                # Sharpness = variance of Laplacian
                lap = ndimage.laplace(block)
                sharpness_values.append(np.var(lap))

        sharp_cv = np.std(sharpness_values) / max(np.mean(sharpness_values), 0.01)
        if sharp_cv < 0.6:
            sharp_score = min(10, int((0.6 - sharp_cv) * 20))
            detail = f"锐度CV={sharp_cv:.2f} (全图太均匀,疑似AI)"
        else:
            sharp_score = 0
            detail = f"锐度CV={sharp_cv:.2f} (有自然对焦/虚化差异)"
        check("锐度均匀性", sharp_score, 10, detail)
    else:
        check("锐度均匀性", 0, 10, "图片太小或scipy不可用")

    # 7. Invisible watermark heuristic (SynthID-like patterns)
    # SynthID embeds in DCT coefficients; we check for suspiciously periodic
    # low-amplitude patterns in the least significant bits
    lsb = img_array.astype(np.int16) & 0x03  # bottom 2 bits
    lsb_flat = lsb[:,:,0].flatten()
    # In natural images, LSB distribution is roughly uniform
    # In watermarked images, there may be periodic structure
    if HAS_SCIPY:
        lsb_fft = np.abs(fft2(lsb[:,:,0].astype(float)))
        lsb_fft_norm = lsb_fft / max(lsb_fft.max(), 1)
        # Check for suspicious peaks (excluding DC)
        lsb_fft_norm[0, 0] = 0
        peak_ratio = np.max(lsb_fft_norm) / max(np.mean(lsb_fft_norm), 0.001)
        if peak_ratio > 15:
            wm_score = min(13, int(peak_ratio / 3))
            detail = f"LSB频域峰值比={peak_ratio:.1f} (可能有隐形水印)"
        else:
            wm_score = 0
            detail = f"LSB频域峰值比={peak_ratio:.1f} (无明显水印特征)"
    else:
        wm_score = 0
        detail = "scipy不可用,无法分析"
    check("隐形水印", wm_score, 13, detail)

    # 8. Edge profile: AI images have more binary edges (strong/weak, lacking gradual transitions)
    # Real cameras + lenses create soft edge profiles; AI diffusion creates unnaturally clean edges
    dx = np.abs(np.diff(luma, axis=1))
    strong_edges = np.sum(dx > 20)
    medium_edges = np.sum((dx > 5) & (dx <= 20))
    edge_ratio = strong_edges / max(medium_edges, 1)
    # Real photos: 0.20-0.30, AI: 0.35-1.05+
    if edge_ratio > 0.35:
        edge_score = min(8, int((edge_ratio - 0.30) * 15))
        detail = f"强弱边缘比={edge_ratio:.3f} (边缘太锐利/二值化)"
    else:
        edge_score = 0
        detail = f"强弱边缘比={edge_ratio:.3f} (自然过渡)"
    check("边缘过渡", edge_score, 8, detail)

    # 9. Channel correlation: real photos have very high RGB correlation (~0.95+)
    # because real illumination affects all channels similarly.
    # AI images often have lower correlation (0.45-0.90) from independent channel generation.
    # Subsample 2D before flatten to avoid 3x full H*W float allocations
    sy, sx = max(1, h // 300), max(1, w // 300)
    r_sub = img_array[::sy, ::sx, 0].ravel().astype(float)
    g_sub = img_array[::sy, ::sx, 1].ravel().astype(float)
    b_sub = img_array[::sy, ::sx, 2].ravel().astype(float)
    rg_corr = np.corrcoef(r_sub, g_sub)[0, 1]
    rb_corr = np.corrcoef(r_sub, b_sub)[0, 1]
    avg_corr = (rg_corr + rb_corr) / 2
    # Real: > 0.94, AI: 0.45-0.90
    if avg_corr < 0.92:
        corr_score = min(8, int((0.92 - avg_corr) * 20))
        detail = f"通道相关={avg_corr:.3f} (RGB不自然,可能独立生成)"
    else:
        corr_score = 0
        detail = f"通道相关={avg_corr:.3f} (自然光照)"
    check("通道相关性", corr_score, 8, detail)

    # Calculate overall risk
    risk_pct = total_score / max(max_score, 1) * 100
    if risk_pct >= 60:
        report["risk_level"] = "HIGH"
    elif risk_pct >= 30:
        report["risk_level"] = "MEDIUM"
    else:
        report["risk_level"] = "LOW"
    report["risk_score"] = round(risk_pct)

    if verbose:
        print("-" * 50)
        level_icon = {"HIGH": "!!!", "MEDIUM": "! ", "LOW": "OK"}[report["risk_level"]]
        print(f"  [{level_icon}] 综合风险: {report['risk_level']} ({report['risk_score']}%)")
        if report["risk_level"] == "HIGH":
            print("  建议: 使用 heavy 预设 + 全部对抗措施")
        elif report["risk_level"] == "MEDIUM":
            print("  建议: 使用 medium 预设即可")
        else:
            print("  建议: light 预设或无需处理")

    return report


# ---------------------------------------------------------------------------
# External AI detection API check
# ---------------------------------------------------------------------------

def check_ai_api(input_path: str, provider: str = "auto", verbose: bool = True) -> dict:
    """
    Check image against external AI detection APIs for a more realistic
    assessment of platform detection risk (closer to what Xiaohongshu/Douyin use).

    Supported providers:
      - sightengine: SightEngine genai model (free 500/mo, needs SIGHTENGINE_USER + SIGHTENGINE_SECRET)
      - isitai: IsItAI API (free 5/mo, needs ISITAI_TOKEN)
      - auto: tries each configured provider in order

    Set env vars: export SIGHTENGINE_USER=xxx SIGHTENGINE_SECRET=xxx
    """
    import urllib.request

    result = {"file": input_path, "provider": None, "ai_probability": None, "label": None, "raw": None}

    # --- SightEngine ---
    se_user = os.environ.get("SIGHTENGINE_USER")
    se_secret = os.environ.get("SIGHTENGINE_SECRET")
    if se_user and se_secret and provider in ("auto", "sightengine"):
        try:
            if verbose:
                print(f"Checking with SightEngine...")
            import mimetypes
            boundary = "----DeAIBoundary"
            filename = os.path.basename(input_path)
            mime = mimetypes.guess_type(input_path)[0] or "image/jpeg"
            with open(input_path, "rb") as f:
                file_data = f.read()
            body = (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"models\"\r\n\r\ngenai\r\n"
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"api_user\"\r\n\r\n{se_user}\r\n"
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"api_secret\"\r\n\r\n{se_secret}\r\n"
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"media\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                "https://api.sightengine.com/1.0/check.json",
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            ai_score = data.get("type", {}).get("ai_generated", 0)
            result["provider"] = "sightengine"
            result["ai_probability"] = round(ai_score * 100, 1)
            result["label"] = "AI" if ai_score > 0.5 else "REAL"
            result["raw"] = data
            if verbose:
                icon = "!!" if ai_score > 0.5 else "OK"
                print(f"  [{icon}] SightEngine: {result['ai_probability']}% AI ({result['label']})")
            return result
        except Exception as e:
            if verbose:
                print(f"  SightEngine error: {e}")
            if provider == "sightengine":
                result["error"] = str(e)
                return result

    # --- IsItAI ---
    isitai_token = os.environ.get("ISITAI_TOKEN")
    if isitai_token and provider in ("auto", "isitai"):
        try:
            if verbose:
                print(f"Checking with IsItAI...")
            boundary = "----DeAIBoundary"
            filename = os.path.basename(input_path)
            with open(input_path, "rb") as f:
                file_data = f.read()
            body = (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"image\"; filename=\"{filename}\"\r\n"
                f"Content-Type: image/jpeg\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
            req = urllib.request.Request(
                "https://api.isitai.com/v2/detect",
                data=body,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Authorization": f"Bearer {isitai_token}",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            confidence = data.get("confidence", 0)
            prediction = data.get("prediction", "unknown")
            result["provider"] = "isitai"
            result["ai_probability"] = round(confidence, 1)
            result["label"] = prediction.upper()
            result["raw"] = data
            if verbose:
                icon = "!!" if prediction == "ai" else "OK"
                print(f"  [{icon}] IsItAI: {confidence}% confidence ({prediction})")
            return result
        except Exception as e:
            if verbose:
                print(f"  IsItAI error: {e}")
            if provider == "isitai":
                result["error"] = str(e)
                return result

    # No provider configured
    if result["provider"] is None:
        result["error"] = "No API configured. Set: SIGHTENGINE_USER+SIGHTENGINE_SECRET or ISITAI_TOKEN"
        if verbose:
            print(f"  [!] {result['error']}")
            print(f"      SightEngine (free 500/mo): https://sightengine.com")
            print(f"      IsItAI (free 5/mo): https://isitai.com")
    return result


# ---------------------------------------------------------------------------
# Invisible watermark disruption
# ---------------------------------------------------------------------------

def disrupt_invisible_watermark(img_array: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """
    Attempt to destroy invisible watermarks (SynthID, C2PA pixel-level, etc.)
    by targeting the low-bit embedding space without visibly degrading the image.

    Strategy:
    1. LSB randomization in perceptually flat areas
    2. Controlled DCT coefficient perturbation
    3. Sub-pixel spatial jitter that disrupts watermark alignment
    4. Color channel micro-offset (breaks cross-channel watermark correlation)
    """
    h, w, c = img_array.shape
    result = img_array.copy().astype(np.float64)

    # 1. LSB perturbation — randomize bottom 1-2 bits in smooth areas
    luma = 0.299 * result[:,:,0] + 0.587 * result[:,:,1] + 0.114 * result[:,:,2]
    if HAS_SCIPY:
        # Detect smooth areas where LSB changes are invisible
        edges = ndimage.sobel(luma)
        smooth_mask = edges < np.percentile(edges, 60)  # bottom 60% smoothest
    else:
        smooth_mask = np.ones((h, w), dtype=bool)

    bits_to_flip = 2 if strength > 0.5 else 1
    for ch in range(c):
        channel = result[:,:,ch].astype(np.int16)
        # Random values for the low bits
        noise = np.random.randint(0, 2**bits_to_flip, (h, w))
        # Clear low bits and set random ones, only in smooth areas
        mask = smooth_mask.astype(np.int16)
        cleared = (channel >> bits_to_flip) << bits_to_flip
        channel = cleared * mask + channel * (1 - mask) + noise * mask
        result[:,:,ch] = channel.astype(np.float64)

    # 2. Sub-pixel spatial displacement (breaks watermark grid alignment)
    if HAS_SCIPY:
        # Very small coherent displacement that doesn't visibly move content
        disp_amp = 0.3 * strength
        dx = np.random.normal(0, disp_amp, (h // 16 + 1, w // 16 + 1))
        dy = np.random.normal(0, disp_amp, (h // 16 + 1, w // 16 + 1))
        dx = ndimage.zoom(dx, (h / (h // 16 + 1), w / (w // 16 + 1)))[:h, :w]
        dy = ndimage.zoom(dy, (h / (h // 16 + 1), w / (w // 16 + 1)))[:h, :w]
        dx = ndimage.gaussian_filter(dx, sigma=8.0)
        dy = ndimage.gaussian_filter(dy, sigma=8.0)

        Y, X = np.mgrid[:h, :w].astype(np.float64)
        for ch in range(c):
            result[:,:,ch] = ndimage.map_coordinates(
                result[:,:,ch], [Y + dy, X + dx],
                order=1, mode='reflect'
            )

    # 3. Cross-channel decorrelation
    # Watermarks often encode the same pattern across R/G/B channels
    # Adding independent micro-noise to each channel breaks this correlation
    for ch in range(c):
        ch_noise = np.random.normal(0, 0.8 * strength, (h, w))
        if HAS_SCIPY:
            ch_noise = ndimage.gaussian_filter(ch_noise, sigma=1.0)
        result[:,:,ch] += ch_noise

    return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Color statistics correction
# ---------------------------------------------------------------------------

def correct_color_statistics(img_array: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """
    AI-generated images have unnaturally smooth, symmetric color histograms.
    Real photos have:
    - Slight highlight clipping (sensor saturation)
    - Shadow noise bump (read noise floor)
    - Asymmetric channel distributions (white balance tint)
    - Occasional histogram gaps from in-camera processing

    This function reshapes the histogram to look more natural.
    """
    result = img_array.astype(np.float64)
    h, w, c = result.shape

    for ch in range(c):
        channel = result[:,:,ch]

        # 1. Add slight highlight roll-off (sensor saturation curve)
        # Real sensors have a soft knee near 255
        highlight_mask = channel > 230
        if np.any(highlight_mask):
            # Compress highlights slightly (soft clipping)
            excess = channel[highlight_mask] - 230
            channel[highlight_mask] = 230 + excess * (0.7 - 0.2 * strength)

        # 2. Add shadow noise floor
        shadow_mask = channel < 20
        if np.any(shadow_mask):
            # Add slight positive bias (read noise floor)
            channel[shadow_mask] += np.random.exponential(1.5 * strength, np.sum(shadow_mask))

        # 3. Per-channel tint shift (white balance imperfection)
        # Real cameras have slight channel offsets from imperfect WB
        tint_offsets = [
            np.random.normal(0, 1.5 * strength),  # R
            np.random.normal(0, 0.5 * strength),  # G (reference, less shift)
            np.random.normal(0, 1.5 * strength),  # B
        ]
        channel += tint_offsets[ch]

        result[:,:,ch] = channel

    return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# JPEG double compression simulation
# ---------------------------------------------------------------------------

def roughen_histogram(img_array: np.ndarray, strength: float = 0.5) -> np.ndarray:
    """
    Make color histogram look like a real camera JPEG — jagged, with uneven bin
    populations. Must run as the LAST pixel operation (after all noise/blur/JPEG)
    because any subsequent smoothing operation will undo it.

    Detection criterion: roughness = mean(|hist - gaussian_smooth(hist)|)
    Threshold: roughness < 0.0005 = flagged as AI-smooth.
    Real camera JPEGs have roughness ~0.001-0.003 from quantization + tone mapping.

    Strategy: selectively deplete and boost specific histogram bins by nudging
    pixel values ±1, creating the characteristic "comb" pattern.
    """
    result = img_array.copy().astype(np.float64)

    for ch in range(3):
        channel = result[:,:,ch]
        flat = channel.flatten()

        # Build histogram to know current bin populations
        hist, _ = np.histogram(flat, bins=256, range=(0, 256))

        # Strategy: completely empty some bins to create zero_bins (passes the
        # zero_bins < 5 check) and redistribute their pixels to neighbors.
        # Also deplete many bins partially to increase roughness above 0.0005.

        # Step A: Create completely empty bins (target 6-10 zero bins)
        # Pick bins with few pixels and move ALL of them out
        n_empty_target = int(5 + 5 * strength)
        small_bins = np.where((hist > 0) & (hist < np.percentile(hist[hist > 0], 20)))[0]
        small_bins = small_bins[(small_bins > 5) & (small_bins < 250)]
        if len(small_bins) > n_empty_target:
            empty_bins = np.random.choice(small_bins, size=n_empty_target, replace=False)
        else:
            empty_bins = small_bins
        for b in empty_bins:
            mask = (flat >= b - 0.5) & (flat < b + 0.5)
            if np.any(mask):
                # Move ALL pixels to ±2
                flat[mask] += np.random.choice([-2.0, 2.0], size=np.sum(mask))

        # Step B: Heavily deplete 25-40% of remaining populated bins
        populated = np.where(hist > 30)[0]
        n_deplete = max(1, int(len(populated) * (0.25 + 0.15 * strength)))
        if len(populated) > n_deplete:
            deplete_bins = np.random.choice(populated, size=n_deplete, replace=False)
        else:
            deplete_bins = populated

        for b in deplete_bins:
            if b in empty_bins:
                continue
            mask = (flat >= b - 0.5) & (flat < b + 0.5)
            n_pixels = np.sum(mask)
            if n_pixels < 10:
                continue
            # Move 50-80% of pixels to ±2..±4
            move_fraction = 0.5 + 0.3 * strength
            n_move = int(n_pixels * move_fraction)
            pixel_indices = np.where(mask)[0]
            move_indices = np.random.choice(pixel_indices, size=min(n_move, len(pixel_indices)), replace=False)
            nudge_range = int(2 + 3 * strength)
            nudges = np.random.randint(-nudge_range, nudge_range + 1, size=len(move_indices)).astype(np.float64)
            nudges[nudges == 0] = np.random.choice([-2.0, 2.0], size=np.sum(nudges == 0))
            flat[move_indices] += nudges

        result[:,:,ch] = flat.reshape(channel.shape)

    return np.clip(result, 0, 255).astype(np.uint8)


def simulate_double_compression(img: Image.Image, quality1: int = 85,
                                 quality2: int = 92) -> Image.Image:
    """
    Real photos often undergo multiple JPEG compressions:
    - Camera saves JPEG (quality ~95)
    - Uploaded to platform, re-compressed (~85)
    - Downloaded and re-saved (~92)

    AI images straight from the generator have ZERO JPEG compression history.
    This simulates realistic double-compression artifacts.
    """
    buf1 = io.BytesIO()
    img.save(buf1, format='JPEG', quality=quality1, subsampling='4:2:0')
    buf1.seek(0)
    img2 = Image.open(buf1).convert('RGB')
    buf2 = io.BytesIO()
    img2.save(buf2, format='JPEG', quality=quality2, subsampling='4:2:0')
    buf2.seek(0)
    return Image.open(buf2).convert('RGB')


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_adaptive_config(scan_report: dict, base_preset: str = "medium") -> dict:
    """
    Build processing config that targets high-risk factors from a scan report.
    Boosts parameters for checks that scored HIGH or MEDIUM risk.
    Returns a config dict ready to use with process_image(config_override=...).
    """
    config = PRESETS[base_preset].copy()
    checks = scan_report.get("checks", {})

    overrides = {}
    targeted = []

    # Track which factors are already OK so we can disable harmful operations
    fft_ok = False
    color_ok = False

    for name, info in checks.items():
        ratio = info["score"] / max(info["max"], 1)

        if "EXIF" in name and ratio > 0.3:
            # EXIF is always injected; no param to boost
            targeted.append(f"EXIF({info['score']}/{info['max']}): 将注入完整相机元数据")

        elif "噪点" in name and ratio > 0.3:
            # Noise uniformity — boost noise intensity
            boost = 0.008 + ratio * 0.022  # range: 0.008 ~ 0.030
            overrides["noise_intensity"] = max(config.get("noise_intensity", 0), boost)
            overrides["noise_color_ratio"] = max(config.get("noise_color_ratio", 0), 0.45)
            targeted.append(f"噪点({info['score']}/{info['max']}): noise={boost:.3f}")

        elif "频域" in name:
            if ratio > 0.5:
                boost = 0.2 + ratio * 0.5
                overrides["fft_perturbation"] = max(config.get("fft_perturbation", 0), boost)
                targeted.append(f"频域({info['score']}/{info['max']}): fft={boost:.2f}")
            elif ratio <= 0.3:
                # FFT perturbation can make symmetry WORSE — disable when already OK
                overrides["fft_perturbation"] = 0
                targeted.append(f"频域({info['score']}/{info['max']}): 已较低,跳过FFT扰动")

        elif "色彩" in name:
            if ratio > 0.5:
                # Only boost color correction when genuinely bad
                boost = 0.2 + ratio * 0.3
                overrides["color_correction"] = max(config.get("color_correction", 0), boost)
                targeted.append(f"色彩({info['score']}/{info['max']}): color_corr={boost:.2f}")
            elif ratio <= 0.3:
                # Color is already OK — DISABLE color correction to avoid making it worse
                overrides["color_correction"] = 0
                targeted.append(f"色彩({info['score']}/{info['max']}): 已正常,跳过色彩校正")

        elif "压缩" in name and ratio > 0.3:
            # Compression layers — enable double compression
            overrides["double_compression"] = True
            targeted.append(f"压缩({info['score']}/{info['max']}): 启用双重压缩")

        elif "锐度" in name:
            if ratio > 0.3:
                boost = 0.4 + ratio * 0.8
                overrides["variable_blur_strength"] = max(config.get("variable_blur_strength", 0), boost)
                targeted.append(f"锐度({info['score']}/{info['max']}): blur={boost:.2f}")
            elif ratio <= 0.15:
                # Sharpness already OK — reduce blur to avoid introducing uniformity penalty
                overrides["variable_blur_strength"] = min(config.get("variable_blur_strength", 0), 0.2)
                targeted.append(f"锐度({info['score']}/{info['max']}): 已正常,减弱模糊")

        elif "水印" in name and ratio > 0.3:
            # Invisible watermark — boost disruption
            boost = 0.4 + ratio * 0.5  # range: 0.4 ~ 0.9
            overrides["invisible_wm_disrupt"] = max(config.get("invisible_wm_disrupt", 0), boost)
            targeted.append(f"隐形水印({info['score']}/{info['max']}): disrupt={boost:.2f}")

    # When FFT symmetry and color histogram are already OK, reduce operations
    # that are known to damage them as side effects
    for name, info in checks.items():
        ratio = info["score"] / max(info["max"], 1)
        if "频域" in name and ratio <= 0.3:
            fft_ok = True
        if "色彩" in name and ratio <= 0.3:
            color_ok = True

    if fft_ok or color_ok:
        # These operations damage FFT symmetry and histogram smoothness
        # as side effects. Reduce when those factors are already passing.
        if fft_ok:
            overrides["chromatic_aberration"] = min(config.get("chromatic_aberration", 0), 0.15)
            overrides["micro_distortion"] = min(config.get("micro_distortion", 0), 0.1)
            overrides["vignette_strength"] = min(config.get("vignette_strength", 0), 0.05)
            overrides["banding_strength"] = 0
        if color_ok:
            overrides["double_compression"] = False
        targeted.append(f"保护模式: {'频域' if fft_ok else ''}{'色彩' if color_ok else ''}已正常,减弱副作用操作")

    config.update(overrides)
    return config, overrides, targeted


def process_image(input_path: str, output_path: str, preset: str = "medium",
                  camera: str = "iphone15", verbose: bool = False,
                  watermark: str = None, config_override: dict = None) -> dict:
    """
    Main processing pipeline. Returns a report dict of what was applied.
    watermark: region to cover — "auto", "BR", "BL", "TR", "TL", or "x,y,w,h"
    config_override: dict of param overrides (from adaptive scan)
    """
    config = PRESETS[preset].copy()
    if config_override:
        config.update(config_override)
    profile = CAMERA_PROFILES[camera]
    mode = config.get("mode", "photo")

    report = {
        "input": input_path,
        "output": output_path,
        "preset": preset,
        "camera": camera,
        "mode": mode,
        "steps": [],
    }

    def log(msg):
        report["steps"].append(msg)
        if verbose:
            print(f"  [+] {msg}")

    if verbose:
        print(f"Processing: {input_path}")
        print(f"Mode: {mode} | Preset: {preset} | Camera: {camera}")

    # Load image
    img = Image.open(input_path).convert("RGB")
    original_size = img.size
    log(f"Loaded {original_size[0]}x{original_size[1]} image")

    # Step 0a: Watermark removal (before any other processing)
    if watermark:
        img = remove_watermark_region(img, region=watermark)
        log(f"Watermark removal: region={watermark}")

    img_array = np.array(img)

    # Step 0b: Invisible watermark disruption (SynthID/C2PA)
    wm_strength = config.get("invisible_wm_disrupt", 0)
    if wm_strength > 0:
        img_array = disrupt_invisible_watermark(img_array, strength=wm_strength)
        log(f"Invisible watermark disruption: strength={wm_strength:.2f}")

    # Step 0c: Color statistics correction
    color_strength = config.get("color_correction", 0)
    if color_strength > 0:
        img_array = correct_color_statistics(img_array, strength=color_strength)
        log(f"Color statistics correction: strength={color_strength:.2f}")

    # Step 1: Frequency domain perturbation (do first to avoid amplifying added noise)
    if HAS_SCIPY and config["fft_perturbation"] > 0:
        img_array = perturb_frequency_domain(img_array, config["fft_perturbation"])
        log(f"FFT high-freq perturbation: strength={config['fft_perturbation']:.2f}")

    if mode == "photo":
        # --- Photo mode pipeline ---

        # Step 2: Micro lens distortion
        if config["micro_distortion"] > 0:
            img_array = add_micro_distortion(img_array, config["micro_distortion"])
            log(f"Micro lens distortion: strength={config['micro_distortion']:.2f}")

        # Step 3: Chromatic aberration
        if config["chromatic_aberration"] > 0:
            img_array = add_chromatic_aberration(img_array, config["chromatic_aberration"])
            log(f"Chromatic aberration: strength={config['chromatic_aberration']:.2f}")

        # Step 4: Variable blur (depth of field simulation)
        if config["variable_blur_strength"] > 0:
            img = Image.fromarray(img_array)
            img = apply_variable_blur_fast(img, config["variable_blur_strength"])
            img_array = np.array(img)
            log(f"Variable blur (DoF): strength={config['variable_blur_strength']:.2f}")

        # Step 5: Sensor noise (intensity-dependent)
        if config["noise_intensity"] > 0:
            img_array = add_sensor_noise(img_array, config["noise_intensity"], config["noise_color_ratio"])
            log(f"Sensor noise: intensity={config['noise_intensity']:.3f}, color_ratio={config['noise_color_ratio']:.1f}")

        # Step 6: Hot pixels
        if config["hot_pixel_count"] > 0:
            img_array = add_hot_pixels(img_array, config["hot_pixel_count"])
            log(f"Hot pixels: count={config['hot_pixel_count']}")

        # Step 7: Banding
        if config["banding_strength"] > 0:
            img_array = add_banding(img_array, config["banding_strength"])
            log(f"Sensor banding: strength={config['banding_strength']:.3f}")

        # Step 8: Vignette
        if config["vignette_strength"] > 0:
            img_array = add_vignette(img_array, config["vignette_strength"])
            log(f"Lens vignette: strength={config['vignette_strength']:.2f}")

    elif mode == "illustration":
        # --- Illustration mode pipeline ---

        # Step 2i: Break gradient uniformity
        if config["gradient_break"] > 0:
            img_array = break_gradient_uniformity(img_array, config["gradient_break"])
            log(f"Gradient break: strength={config['gradient_break']:.2f}")

        # Step 3i: Micro jitter (hand-drawn imperfection)
        if config["micro_jitter"] > 0:
            img_array = add_micro_jitter(img_array, config["micro_jitter"])
            log(f"Micro jitter: strength={config['micro_jitter']:.2f}")

        # Step 4i: Paper/canvas texture
        if config["paper_texture"] > 0:
            img_array = add_paper_texture(img_array, config["paper_texture"])
            log(f"Paper texture: strength={config['paper_texture']:.2f}")

        # Step 5i: Very subtle noise (not sensor noise, more like compression artifact)
        if config["noise_intensity"] > 0:
            img_array = add_sensor_noise(img_array, config["noise_intensity"], config["noise_color_ratio"])
            log(f"Subtle noise: intensity={config['noise_intensity']:.3f}")

    # Final image
    img = Image.fromarray(img_array)

    # JPEG double compression simulation
    double_comp = config.get("double_compression", False)
    if double_comp:
        img = simulate_double_compression(img, quality1=83, quality2=config["jpeg_quality"])
        log(f"JPEG double compression: q1=83 -> q2={config['jpeg_quality']}")

    # Generate EXIF
    exif_bytes = generate_exif(profile)
    if exif_bytes:
        log(f"EXIF injected: {profile['make']} {profile['model']}, ISO range {profile['iso']}")
    else:
        log("EXIF skipped (piexif not available)")

    # Save with camera quantization tables
    save_with_quantization_tables(img, output_path, profile, config["jpeg_quality"], exif_bytes)
    log(f"JPEG saved: quality={config['jpeg_quality']}, QT={camera}")

    # Post-JPEG histogram roughening — compensate for pipeline smoothing
    # Strategy: read back saved JPEG, apply strong roughening (±3-5 bin nudges),
    # then save at LOWER quality (Q75) so JPEG quantization artifacts themselves
    # add permanent roughness that can't be smoothed away.
    roughen_strength = 0.5
    saved_img = Image.open(output_path)
    saved_array = np.array(saved_img)
    saved_array = roughen_histogram(saved_array, strength=roughen_strength)
    # Q75 creates enough DCT quantization artifacts for natural histogram roughness
    final_q = max(85, config["jpeg_quality"] - 6)
    roughened_img = Image.fromarray(saved_array)
    save_kwargs = {"format": "JPEG", "quality": final_q, "subsampling": "4:2:0"}
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes
    roughened_img.save(output_path, **save_kwargs)
    log(f"Post-JPEG histogram roughening: strength={roughen_strength:.2f}, q={final_q}")

    output_size = os.path.getsize(output_path)
    log(f"Output: {output_path} ({output_size / 1024:.0f} KB)")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Remove AI-generated image artifacts. Works with photos, illustrations, cartoons, and AI text images.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  photo          Simulate real camera output (sensor noise, DoF, lens effects)
  illustration   For cartoons/illustrations (paper texture, gradient break, jitter)

Presets (photo mode):
  light    Subtle, good for high-quality AI photos
  medium   Balanced (default)
  heavy    Aggressive, simulates high-ISO / low-light

Presets (illustration mode):
  illust-light    Subtle paper texture + gradient variation
  illust-medium   Balanced illustration processing (default for --mode illustration)
  illust-heavy    Strong paper grain + jitter + gradient break

Cameras:
  iphone15   Apple iPhone 15 Pro Max (default)
  canon_r5   Canon EOS R5
  sony_a7iv  Sony A7 IV
  nikon_z8   Nikon Z 8

Watermark removal:
  auto       Auto-detect watermark position
  BR/BL/TR/TL   Bottom-right / bottom-left / top-right / top-left
  x,y,w,h    Manual coordinates

Examples:
  %(prog)s photo.png -o real_photo.jpg
  %(prog)s cartoon.png --mode illustration -o output.jpg
  %(prog)s ai_art.png --mode illustration --preset illust-heavy --watermark auto
  %(prog)s photo.png --preset heavy --camera canon_r5 --watermark BR
        """
    )
    parser.add_argument("input", help="Input image path or directory (batch mode)")
    parser.add_argument("-o", "--output", help="Output path: file (single) or directory (batch)")
    parser.add_argument("--mode", choices=["photo", "illustration"], default=None,
                        help="Processing mode (default: auto-select based on preset)")
    parser.add_argument("--preset",
                        choices=["light", "medium", "heavy", "illust-light", "illust-medium", "illust-heavy"],
                        default=None,
                        help="Processing intensity (default: medium for photo, illust-medium for illustration)")
    parser.add_argument("--camera", choices=list(CAMERA_PROFILES.keys()), default="iphone15",
                        help="Camera profile for EXIF/quantization (default: iphone15)")
    parser.add_argument("--watermark", default=None,
                        help="Remove watermark: auto, BR, BL, TR, TL, or x,y,w,h")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print processing steps")
    parser.add_argument("--json", action="store_true", help="Output report as JSON")
    parser.add_argument("--scan", action="store_true",
                        help="Scan image for AI detection risk (no processing, report only)")
    parser.add_argument("--check-api", action="store_true",
                        help="Check with external AI detection API (needs SIGHTENGINE_USER+SECRET or ISITAI_TOKEN)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    # --- Scan-only mode ---
    # --- check-api mode ---
    if args.check_api:
        result = check_ai_api(args.input, verbose=True)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        sys.exit(0)

    if args.scan:
        use_verbose = not args.json
        if os.path.isdir(args.input):

            input_dir = Path(args.input)
            image_files = sorted(
                f for f in input_dir.iterdir()
                if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.')
            )
            for img_path in image_files:
                report = scan_image(str(img_path), verbose=use_verbose)
                if args.json:
                    print(json.dumps(report, indent=2, ensure_ascii=False))
                if use_verbose:
                    print()
        else:
            report = scan_image(args.input, verbose=use_verbose)
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Resolve preset based on mode
    if args.preset is None:
        if args.mode == "illustration":
            args.preset = "illust-medium"
        else:
            args.preset = "medium"

    # If mode is explicitly set but preset doesn't match, adjust
    if args.mode == "illustration" and args.preset in ("light", "medium", "heavy"):
        args.preset = f"illust-{args.preset}"
    elif args.mode == "photo" and args.preset.startswith("illust-"):
        args.preset = args.preset.replace("illust-", "")

    # --- Batch mode: input is a directory ---
    if os.path.isdir(args.input):

        input_dir = Path(args.input)
        image_files = sorted(
            f for f in input_dir.iterdir()
            if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.')
        )

        if not image_files:
            print(f"Error: no images found in {args.input}", file=sys.stderr)
            sys.exit(1)

        # Output directory
        if args.output:
            out_dir = Path(args.output)
        else:
            out_dir = input_dir / "deai_output"
        out_dir.mkdir(parents=True, exist_ok=True)

        total = len(image_files)
        reports = []
        success = 0
        failed = 0

        print(f"Batch: {total} images in {input_dir}")
        print(f"Output: {out_dir}")
        print(f"Mode: {args.mode or 'auto'} | Preset: {args.preset} | Camera: {args.camera}")
        print("-" * 50)

        for i, img_path in enumerate(image_files, 1):
            out_path = str(out_dir / f"{img_path.stem}_deai.jpg")
            try:
                print(f"[{i}/{total}] {img_path.name} ", end="", flush=True)
                report = process_image(
                    str(img_path), out_path,
                    preset=args.preset,
                    camera=args.camera,
                    verbose=False,
                    watermark=args.watermark,
                )
                reports.append(report)
                out_size = os.path.getsize(out_path)
                print(f"-> {out_size/1024:.0f} KB")
                success += 1
            except Exception as e:
                print(f"FAILED: {e}")
                failed += 1

        print("-" * 50)
        print(f"Done: {success} success, {failed} failed")
        print(f"Output dir: {out_dir}")

        if args.json:
            print(json.dumps({"batch": True, "total": total, "success": success,
                              "failed": failed, "output_dir": str(out_dir),
                              "reports": reports}, indent=2))
        sys.exit(0)

    # --- Single file mode ---
    if args.output is None:
        stem = Path(args.input).stem
        parent = Path(args.input).parent
        args.output = str(parent / f"{stem}_deai.jpg")

    report = process_image(
        args.input,
        args.output,
        preset=args.preset,
        camera=args.camera,
        verbose=args.verbose,
        watermark=args.watermark,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    elif not args.verbose:
        print(f"Done: {args.output}")


if __name__ == "__main__":
    main()
