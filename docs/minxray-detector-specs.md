# MinXray Detector Specs & Synthetic Capture Plan

Context for simulating MinXray DR captures from public-domain chest X-ray PNGs (IMLADRIS imaging integration lab).
Compiled 2026-09-29 from MinXray product pages and reseller spec sheets (sources at bottom).

## Detector configurations

| Panel (typical system) | Matrix (W x H) | Pixel pitch | Field | A/D | Output |
|---|---|---|---|---|---|
| 14x17 wireless CsI (CMDR Wireless, Impact Wireless) | 2304 x 2816 | 154 um | 35 x 43 cm | 16-bit | 16-bit grayscale |
| 14x17 tethered CsI, Toshiba FDX3543RP (CMDR-2S, original Impact, military variants) | 2448 x 2984 | 140 um | 35 x 43 cm | 14-bit | 16-bit grayscale TIFF |
| 10x12 CsI (Enduras) | 2048 x 2560 | 120 um | 24.4 x 30.7 cm | - | 16-bit grayscale |

Image quality figures:
- 14x17 wireless: MTF 40% @ 2 lp/mm, DQE(0) 65% typ
- 14x17 Toshiba tethered: MTF 36% @ 2 lp/mm, DQE(0) 70% typ

Software: MinXView acquisition software, DICOM 3.0 compliant. It can be bundled with Qure.ai qXR, a chest AI used for TB screening.

**Default target:** 14x17 wireless panel, 2304 x 2816 @ 0.154 mm.

## Unknowns (need a real MinXView DICOM sample or MinXray conformance statement)
- Modality tag (DX vs CR)
- PhotometricInterpretation (MONOCHROME1 vs MONOCHROME2)
- BitsStored (14 vs 16), WindowCenter/Width defaults
- "For Processing" vs "For Presentation" export behavior
- Manufacturer / model / software version tag values

## Conversion pipeline (PNG -> synthetic MinXray DICOM)

Public PNGs are 8-bit and already post-processed. The goal is statistical and geometric plausibility, not recovery of true raw data.

1. **Geometry:** Resample to the target matrix at the target pitch. Scale the anatomy realistically, since a PA chest doesn't fill 43 cm. Pad the image and add collimation borders.
2. **Bit depth:** Map to 16-bit, or 14 bits stored in a 16-bit container. Optionally apply an approximate inverse log/contrast curve to get a "for processing"-style image.
3. **Detector physics:**
   - Gaussian/MTF blur tuned to about 0.36-0.40 at 2 lp/mm
   - Poisson quantum noise, with dose level as a parameter
   - Gaussian electronic noise floor
   - Optional: gain/offset nonuniformity, dead line/pixel
4. **DICOM output (pydicom):** Write a DX image with Rows/Columns, ImagerPixelSpacing, BitsAllocated/BitsStored and patient/study UIDs.
   - **Mark it synthetic:** set ImageType `DERIVED\SECONDARY` and put a DerivationDescription naming the source PNG and the simulation parameters.
   - Use obviously fake patient demographics so these are never mistaken for real captures in PACS.

Script parameters: `--panel {wireless154,toshiba140,enduras120}`, `--dose`, `--seed`, `--out-format {dcm,tiff}`.

## Sources
- https://www.minxray.com/cmdr2s-wireless
- https://www.minxray.com/enduras-wireless
- https://www.minxray.com/cmdr-2s-tmil
- https://proximusmedical.com/product/minxray-impact-portable-x-ray-machine/
- https://proximusmedical.com/product/minxray-cmdr-2s/
- https://www.minxray.com/post/ai-software-included-on-portable-digital-radiography-systems-from-minxray
