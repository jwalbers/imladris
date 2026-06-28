#!/usr/bin/env python3
"""
extract_cxr_from_qure.py — Extract clean CXR images from Qure.ai annotated PNGs.

Qure.ai output PNGs are 1581x792 RGBA with two panels:
  Left:  CXR image with annotation overlays (bezier region outlines, callout
         text boxes, corner labels — all rendered as white/bright-gray on the
         grayscale X-ray)
  Right: qXR Interpretation report panel (dark background, white text)

This tool:
  1. Detects the panel boundary and crops the CXR portion
  2. Removes annotation overlays via bright-pixel masking + OpenCV inpainting
  3. Saves clean 8-bit grayscale PNG files suitable for use as primary DICOM captures

Usage:
    source ../.imladris_venv/bin/activate
    python3 extract_cxr_from_qure.py \
        --input-dir "/Volumes/BURT_H/PIH/extracted/CXRs from qtrack" \
        --output-dir /Volumes/BURT_H/PIH/extracted/CXRs_clean \
        [--threshold 230] [--dilate 6] [--min-area 200] [--dry-run]
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from skimage import measure, morphology


# ── CLI ───────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Extract clean CXR images from Qure.ai PNGs")
parser.add_argument("--input-dir",
    default="/Volumes/BURT_H/PIH/extracted/CXRs from qtrack",
    help="Directory containing Qure.ai annotated PNGs")
parser.add_argument("--output-dir",
    default="/Volumes/BURT_H/PIH/extracted/CXRs_clean",
    help="Output directory for clean grayscale CXR PNGs")
parser.add_argument("--threshold", type=int, default=228,
    help="Brightness threshold for annotation detection (default 228)")
parser.add_argument("--dilate", type=int, default=7,
    help="Dilation radius (pixels) applied to annotation mask (default 7)")
parser.add_argument("--min-area", type=int, default=8,
    help="Min connected-component area to include in mask (default 8)")
parser.add_argument("--dry-run", action="store_true",
    help="Process first image only, save annotated debug image to output dir")
args = parser.parse_args()


# ── Panel detection ───────────────────────────────────────────────────────────

def detect_panel_width(rgba: np.ndarray) -> int:
    """Return the x-coordinate of the right edge of the CXR panel.

    Uses per-column MEDIAN brightness (searched in left 75% of image).
    Median stays low in the report panel even where white text creates
    bright pixels, because the background dominates numerically.
    """
    h, w = rgba.shape[:2]
    gray = rgba[:, :int(w * 0.75), 0]
    col_median = np.median(gray, axis=0)
    # Rightmost column where median > 45 is the last column of CXR anatomy
    cxr_cols = np.where(col_median > 45)[0]
    if len(cxr_cols):
        return int(cxr_cols.max()) + 15
    return int(w * 0.55)


# ── Annotation mask ───────────────────────────────────────────────────────────

def build_annotation_masks(gray: np.ndarray, threshold: int, dilate_r: int,
                            min_area: int):
    """
    Return (inpaint_mask, zero_fill_mask) — both uint8, 255 = region to remove.

    Two annotation types need different removal strategies:

    BEZIER OUTLINES (large components ≥ 1000px area)
        Thin closed curves drawn over lung tissue → inpaint from surrounding tissue.

    CALLOUT BOXES (clusters of small text/border fragments)
        Dark overlay boxes with white text, always placed at the image edge near
        the black CXR border. Inpainting creates a gray smear because it tries to
        interpolate between black border and lung tissue. Correct answer is black
        (0), matching the background the box was placed on top of.
        Strategy: dilate small bright fragments by 30px to merge them into cluster
        blobs, fill each cluster's bounding box. Boxes touching within edge_margin
        of any image edge → zero_fill_mask. Interior boxes (rare) → inpaint_mask.

    CORNER MASK (top 10% × left 30%)
        Qure.ai icon + "Normal/Abnormal" label, always black background → zero_fill.
    """
    h, w = gray.shape
    bright = (gray >= threshold).astype(np.uint8)

    labeled = measure.label(bright)
    props = measure.regionprops(labeled)

    bezier_mask = np.zeros_like(bright)
    small_mask  = np.zeros_like(bright)

    for p in props:
        if p.area < min_area:
            continue
        if p.area >= 1000:
            bezier_mask[labeled == p.label] = 1
        else:
            small_mask[labeled == p.label] = 1

    # Also detect the corner "Normal/Abnormal" label rendered at lower brightness
    # (Qure.ai renders it at ~170-210, below the 215 global threshold)
    corner_h = int(h * 0.12)
    corner_w = int(w * 0.50)
    bright_corner = (gray[:corner_h, :corner_w] >= 170).astype(np.uint8)
    bright_corner[bright[:corner_h, :corner_w] > 0] = 0  # already in main mask
    for p in measure.regionprops(measure.label(bright_corner)):
        if 4 <= p.area < 300:    # text-sized: not noise, not bone
            small_mask[:corner_h, :corner_w][
                measure.label(bright_corner) == p.label] = 1

    # The callout box INTERIOR is always very dark (0-30), visually the same as the
    # CXR's own black border — it disappears naturally once the bright outline/text
    # pixels are removed. So: zero-fill only the detected bright pixels + a small
    # dilation to cover anti-aliasing. No bbox expansion, no interior fill needed.
    # Bezier outlines (large, over lung tissue) still get inpainted from surrounding.
    selem = morphology.disk(dilate_r)
    inpaint_mask   = morphology.dilation(bezier_mask, selem).astype(np.uint8) * 255
    zero_fill_mask = morphology.dilation(small_mask,  selem).astype(np.uint8) * 255

    return inpaint_mask, zero_fill_mask


# ── Main processing ───────────────────────────────────────────────────────────

def process(png_path: Path, out_dir: Path, threshold: int, dilate_r: int,
            min_area: int, debug: bool = False) -> Path:
    img = Image.open(png_path)
    rgba = np.array(img)

    # 1. Crop CXR panel
    panel_w = detect_panel_width(rgba)
    gray = rgba[:, :panel_w, 0]  # R == G == B for all pixels

    # 2. Build annotation masks
    inpaint_mask, zero_fill_mask = build_annotation_masks(gray, threshold, dilate_r, min_area)

    # 3a. Zero-fill edge callout boxes (over black CXR border — correct answer is 0)
    result = gray.copy()
    result[zero_fill_mask > 0] = 0

    # 3b. Inpaint interior bezier outlines from surrounding tissue.
    #     Mirror-pad so pixels at the image boundary have neighbours to borrow from.
    pad = 40
    rpad = cv2.copyMakeBorder(result, pad, pad, pad, pad, cv2.BORDER_REFLECT_101)
    mpad = cv2.copyMakeBorder(inpaint_mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    rpad2 = cv2.inpaint(rpad, mpad, inpaintRadius=6, flags=cv2.INPAINT_TELEA)
    clean = rpad2[pad:-pad, pad:-pad]

    if debug:
        orig_rgb  = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        zmask_rgb = cv2.cvtColor(zero_fill_mask, cv2.COLOR_GRAY2BGR)
        imask_rgb = cv2.cvtColor(inpaint_mask,   cv2.COLOR_GRAY2BGR)
        clean_rgb = cv2.cvtColor(clean, cv2.COLOR_GRAY2BGR)
        debug_img = np.hstack([orig_rgb, zmask_rgb, imask_rgb, clean_rgb])
        debug_path = out_dir / f"DEBUG_{png_path.stem}.png"
        cv2.imwrite(str(debug_path), debug_img)
        print(f"  Debug image: {debug_path}")

    # 4. Save clean grayscale PNG
    out_path = out_dir / png_path.name
    cv2.imwrite(str(out_path), clean)
    return out_path


def main():
    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pngs = sorted(in_dir.glob("*.png"))
    if not pngs:
        print(f"No PNG files found in {in_dir}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        pngs = pngs[:1]
        print(f"Dry run — processing {pngs[0].name} only")

    print(f"Processing {len(pngs)} image(s)  threshold={args.threshold}  "
          f"dilate={args.dilate}  min_area={args.min_area}")

    for i, p in enumerate(pngs, 1):
        out = process(p, out_dir, args.threshold, args.dilate, args.min_area,
                      debug=args.dry_run)
        print(f"  [{i:3}/{len(pngs)}] {p.name} → {out.name}")

    print(f"\nDone. Clean CXRs in {out_dir}")


if __name__ == "__main__":
    main()
