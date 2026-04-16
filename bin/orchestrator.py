#!/usr/bin/env python3
"""
DeAI Orchestrator — deterministic orchestration layer.
Replaces all Claude ad-hoc decisions with codified logic.
Ensures identical behavior across any computer, platform, or AI agent.

Usage:
    # Auto mode: scan → auto-detect → smart fix → report
    python3 orchestrator.py auto <input> [-o output]

    # Scan only
    python3 orchestrator.py scan <input>

    # Process with explicit params
    python3 orchestrator.py process <input> [-o output] [--mode photo|illustration] [--preset ...] [--camera ...]

    # Web panel
    python3 orchestrator.py web [--port 8890]

    # Batch auto
    python3 orchestrator.py auto <folder> [-o output_folder]
"""

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
import deai


# ---------------------------------------------------------------------------
# L1: Image classifier — replaces Claude's "看图判断"
# ---------------------------------------------------------------------------

def classify_image(input_path: str) -> dict:
    """
    Deterministic image classification. Returns:
      mode: "photo" | "illustration"
      has_watermark: bool
      recommended_preset: str
      recommended_camera: str
      reason: str
    """
    from PIL import Image
    import numpy as np

    img = Image.open(input_path).convert("RGB")
    arr = np.array(img)
    h, w, _ = arr.shape

    # --- Mode detection: photo vs illustration ---
    # Illustration signals: limited color palette, flat regions, hard edges
    # Photo signals: continuous gradients, high color count, noise

    # 1. Unique color count (subsample for speed)
    subsample = arr[::4, ::4].reshape(-1, 3)
    # Quantize to 32 levels per channel to count "perceptual" colors
    quantized = (subsample // 8).astype(np.uint32)
    color_ids = quantized[:, 0] * 1024 + quantized[:, 1] * 32 + quantized[:, 2]
    unique_colors = len(np.unique(color_ids))
    total_pixels = len(color_ids)
    color_ratio = unique_colors / total_pixels  # high = photo-like

    # 2. Edge density (Sobel-like)
    gray = 0.299 * arr[:, :, 0].astype(float) + 0.587 * arr[:, :, 1].astype(float) + 0.114 * arr[:, :, 2].astype(float)
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    edge_density = (np.mean(dx) + np.mean(dy)) / 2

    # 3. Flat region ratio (std < 3 in 16x16 blocks)
    block_size = 16
    flat_count = 0
    total_blocks = 0
    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            block = gray[y:y + block_size, x:x + block_size]
            if np.std(block) < 3.0:
                flat_count += 1
            total_blocks += 1
    flat_ratio = flat_count / max(total_blocks, 1)

    # Decision logic
    # Illustration: low color_ratio OR high flat_ratio OR low edge_density
    illustration_score = 0
    if color_ratio < 0.15:
        illustration_score += 2
    if flat_ratio > 0.3:
        illustration_score += 2
    if edge_density < 8:
        illustration_score += 1

    mode = "illustration" if illustration_score >= 3 else "photo"
    reason_parts = []
    if mode == "illustration":
        reason_parts.append(f"color_ratio={color_ratio:.3f}")
        reason_parts.append(f"flat_ratio={flat_ratio:.2f}")
        reason_parts.append(f"edge_density={edge_density:.1f}")

    # --- Watermark detection ---
    has_watermark = False
    try:
        candidates = deai._detect_watermark_candidates(np.array(img))
        has_watermark = len(candidates) > 0
    except Exception:
        pass

    # --- Preset selection based on scan ---
    # Will be overridden by smart_fix if used, but provide a sensible default
    recommended_preset = "medium" if mode == "photo" else "illust-medium"

    # --- Camera selection ---
    # Default to iPhone for social media use case (most common)
    recommended_camera = "iphone15"

    return {
        "mode": mode,
        "has_watermark": has_watermark,
        "recommended_preset": recommended_preset,
        "recommended_camera": recommended_camera,
        "reason": f"mode={mode} ({', '.join(reason_parts) if reason_parts else 'photo-like continuous tones'}), watermark={'yes' if has_watermark else 'no'}",
        "metrics": {
            "color_ratio": round(color_ratio, 4),
            "flat_ratio": round(flat_ratio, 3),
            "edge_density": round(edge_density, 2),
            "illustration_score": illustration_score,
        }
    }


# ---------------------------------------------------------------------------
# L2: Preset selector — replaces Claude's "感觉选 preset"
# ---------------------------------------------------------------------------

def select_preset(scan_report: dict, mode: str) -> str:
    """
    Deterministic preset selection based on scan risk score.
    """
    score = scan_report.get("risk_score", 50)

    if mode == "photo":
        if score >= 60:
            return "heavy"
        elif score >= 30:
            return "medium"
        else:
            return "light"
    else:
        if score >= 60:
            return "illust-heavy"
        elif score >= 30:
            return "illust-medium"
        else:
            return "illust-light"


# ---------------------------------------------------------------------------
# L3: Smart fix pipeline — the full scan → config → process → rescan flow
# ---------------------------------------------------------------------------

def smart_fix(input_path: str, output_path: str, camera: str = "iphone15",
              verbose: bool = True) -> dict:
    """
    Complete auto pipeline:
    1. Classify image → mode
    2. Scan → risk score
    3. Select preset based on score
    4. Build adaptive config targeting high-risk factors
    5. Process with protection mode
    6. Re-scan output
    7. Return full report with before/after comparison
    """
    result = {
        "input": input_path,
        "output": output_path,
    }

    # Step 1: Classify
    classification = classify_image(input_path)
    mode = classification["mode"]
    result["classification"] = classification

    if verbose:
        print(f"[1/6] Classification: {classification['reason']}")

    # Step 2: Scan
    scan_before = deai.scan_image(input_path, verbose=False)
    result["scan_before"] = scan_before

    if verbose:
        print(f"[2/6] Scan: {scan_before['risk_score']}% ({scan_before['risk_level']})")

    # Step 3: Select preset
    preset = select_preset(scan_before, mode)
    result["preset"] = preset

    if verbose:
        print(f"[3/6] Preset: {preset}")

    # Step 4: Build adaptive config
    adaptive_config, overrides, targeted = deai.build_adaptive_config(scan_before, preset)
    result["targeted"] = targeted

    if verbose:
        print(f"[4/6] Adaptive config: {len(overrides)} overrides")
        for t in targeted:
            print(f"      {t}")

    # Step 5: Process
    watermark = "auto" if classification["has_watermark"] else None
    process_report = deai.process_image(
        input_path, output_path,
        preset=preset,
        camera=camera,
        verbose=verbose,
        watermark=watermark,
        config_override=overrides,
    )
    result["steps"] = process_report["steps"]
    result["camera"] = camera
    result["mode"] = mode

    if verbose:
        print(f"[5/6] Processing complete: {len(process_report['steps'])} steps")

    # Step 6: Re-scan
    scan_after = deai.scan_image(output_path, verbose=False)
    result["scan_after"] = scan_after

    drop = scan_before["risk_score"] - scan_after["risk_score"]
    result["risk_drop"] = drop

    # Step 7: SSIM quality check — ensure processing didn't degrade image too much
    from PIL import Image
    import numpy as np
    orig_arr = np.array(Image.open(input_path).convert("RGB")).astype(float)
    proc_arr = np.array(Image.open(output_path).convert("RGB")).astype(float)
    # Resize if dimensions differ
    if orig_arr.shape != proc_arr.shape:
        proc_img = Image.open(output_path).convert("RGB").resize(
            (orig_arr.shape[1], orig_arr.shape[0]), Image.LANCZOS)
        proc_arr = np.array(proc_img).astype(float)
    # Simple SSIM approximation (luminance + contrast)
    mu_x, mu_y = np.mean(orig_arr), np.mean(proc_arr)
    sig_x, sig_y = np.std(orig_arr), np.std(proc_arr)
    sig_xy = np.mean((orig_arr - mu_x) * (proc_arr - mu_y))
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ssim = ((2 * mu_x * mu_y + C1) * (2 * sig_xy + C2)) / \
           ((mu_x ** 2 + mu_y ** 2 + C1) * (sig_x ** 2 + sig_y ** 2 + C2))
    result["ssim"] = round(ssim, 4)

    quality_ok = ssim >= 0.85
    result["quality_ok"] = quality_ok

    if verbose:
        print(f"[6/7] Result: {scan_before['risk_score']}% → {scan_after['risk_score']}% (dropped {drop} pts)")
        ssim_icon = "OK" if quality_ok else "!!"
        print(f"[7/7] SSIM: {ssim:.4f} [{ssim_icon}] {'画质正常' if quality_ok else '画质损失较大,建议用 light 预设'}")
        print()
        print("Per-factor comparison:")
        for name in scan_before["checks"]:
            b = scan_before["checks"][name]
            a = scan_after["checks"].get(name, b)
            d = b["score"] - a["score"]
            marker = f"+{d}" if d > 0 else str(d) if d < 0 else "="
            print(f"  {name}: {b['score']}/{b['max']} → {a['score']}/{a['max']}  [{marker}]")

    return result


# ---------------------------------------------------------------------------
# L4: Batch processor
# ---------------------------------------------------------------------------

def batch_auto(input_dir: str, output_dir: str, camera: str = "iphone15",
               verbose: bool = True) -> dict:
    """
    Batch auto-process all images in a directory.
    Each image gets its own classification → scan → adaptive process cycle.
    """
    IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    image_files = sorted(
        f for f in input_path.iterdir()
        if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.')
    )

    if not image_files:
        print(f"No images found in {input_dir}")
        return {"success": 0, "failed": 0, "results": []}

    results = []
    success = 0
    failed = 0

    for i, img_file in enumerate(image_files):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(image_files)}] {img_file.name}")
        print(f"{'='*60}")

        out_file = output_path / f"{img_file.stem}_deai.jpg"

        try:
            result = smart_fix(
                str(img_file), str(out_file),
                camera=camera, verbose=verbose
            )
            results.append(result)
            success += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"input": str(img_file), "error": str(e)})
            failed += 1

    print(f"\n{'='*60}")
    print(f"Batch complete: {success} success, {failed} failed")
    print(f"Output: {output_path}")

    return {"success": success, "failed": failed, "results": results}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="DeAI Orchestrator — deterministic AI artifact removal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  auto      Full auto pipeline: classify → scan → adaptive fix → verify
  scan      Scan image for AI detection risk (no processing)
  process   Process with explicit parameters
  web       Start web panel
  classify  Classify image type (photo/illustration)

Examples:
  orchestrator.py auto photo.png
  orchestrator.py auto ~/ai_images/ -o ~/processed/
  orchestrator.py scan photo.png
  orchestrator.py scan photo.png --json
  orchestrator.py process photo.png --mode photo --preset heavy --camera canon_r5
  orchestrator.py web --port 8890
  orchestrator.py classify photo.png
""")

    parser.add_argument("command", choices=["auto", "scan", "process", "web", "classify", "check"],
                        help="Command to run")
    parser.add_argument("input", nargs="?", help="Input image or directory")
    parser.add_argument("-o", "--output", help="Output path")
    parser.add_argument("--mode", choices=["photo", "illustration"], help="Processing mode (auto if omitted)")
    parser.add_argument("--preset", help="Preset name")
    parser.add_argument("--camera", default="iphone15", help="Camera profile (default: iphone15)")
    parser.add_argument("--port", type=int, default=8890, help="Web panel port")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # --- web ---
    if args.command == "web":
        import subprocess
        server_path = SCRIPT_DIR / "server.py"
        subprocess.run([sys.executable, str(server_path), "--port", str(args.port)])
        return

    # All other commands need input
    if not args.input:
        parser.error(f"Command '{args.command}' requires an input path")

    if not os.path.exists(args.input):
        print(f"Error: {args.input} not found", file=sys.stderr)
        sys.exit(1)

    # --- check (external API) ---
    if args.command == "check":
        result = deai.check_ai_api(args.input, verbose=True)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    # --- classify ---
    if args.command == "classify":
        result = classify_image(args.input)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"Mode: {result['mode']}")
            print(f"Watermark: {'yes' if result['has_watermark'] else 'no'}")
            print(f"Preset: {result['recommended_preset']}")
            print(f"Reason: {result['reason']}")
            print(f"Metrics: {json.dumps(result['metrics'], indent=2)}")
        return

    # --- scan ---
    if args.command == "scan":
        if os.path.isdir(args.input):
            IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'}
            for f in sorted(Path(args.input).iterdir()):
                if f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('.'):
                    report = deai.scan_image(str(f), verbose=not args.json)
                    if args.json:
                        print(json.dumps(report, indent=2, ensure_ascii=False))
                    print()
        else:
            report = deai.scan_image(args.input, verbose=not args.json)
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
        return

    # --- auto ---
    if args.command == "auto":
        if os.path.isdir(args.input):
            out_dir = args.output or str(Path(args.input) / "deai_output")
            result = batch_auto(args.input, out_dir, camera=args.camera, verbose=True)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            output = args.output or str(Path(args.input).with_stem(Path(args.input).stem + "_deai").with_suffix(".jpg"))
            result = smart_fix(args.input, output, camera=args.camera, verbose=True)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return

    # --- process ---
    if args.command == "process":
        # Explicit mode — no auto-detection
        if not args.output:
            args.output = str(Path(args.input).with_stem(Path(args.input).stem + "_deai").with_suffix(".jpg"))

        mode = args.mode
        preset = args.preset

        # If mode not specified, auto-classify
        if not mode:
            cls = classify_image(args.input)
            mode = cls["mode"]
            print(f"Auto-detected mode: {mode}")

        # If preset not specified, use default for mode
        if not preset:
            preset = "medium" if mode == "photo" else "illust-medium"

        # Adjust preset name for illustration mode
        if mode == "illustration" and not preset.startswith("illust-"):
            preset = f"illust-{preset}"

        report = deai.process_image(
            args.input, args.output,
            preset=preset,
            camera=args.camera,
            verbose=True,
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
