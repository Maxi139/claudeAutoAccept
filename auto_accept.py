#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import mss
import numpy as np
import pyautogui


DEFAULT_TEMPLATE = Path(__file__).with_name("Bildschirmfoto 2026-03-26 um 20.16.46.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search the main display for a template and click the match center."
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="Path to the template image.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds to wait between scans.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.48,
        help="Normalized template matching threshold from 0.0 to 1.0.",
    )
    parser.add_argument(
        "--min-scale",
        type=float,
        default=0.40,
        help="Smallest scale factor to test for the template.",
    )
    parser.add_argument(
        "--max-scale",
        type=float,
        default=1.25,
        help="Largest scale factor to test for the template.",
    )
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="Increment between tested template scales.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect matches without clicking.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the best score for every scan.",
    )
    parser.add_argument(
        "--min-good-matches",
        type=int,
        default=4,
        help="Minimum SIFT good matches required before clicking.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def load_template(template_path: Path) -> np.ndarray:
    if not template_path.is_file():
        raise FileNotFoundError(f"Template not found: {template_path}")

    template = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
    if template is None:
        raise ValueError(f"Failed to load template image: {template_path}")

    if template.ndim == 3 and template.shape[2] == 4:
        template = cv2.cvtColor(template, cv2.COLOR_BGRA2BGR)

    if template.ndim == 3:
        return cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    return template


def capture_main_screen(sct: mss.mss) -> tuple[np.ndarray, dict]:
    monitor = dict(sct.monitors[1])
    shot = sct.grab(monitor)
    frame = np.array(shot)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    return gray, monitor


def find_match(
    haystack: np.ndarray,
    needle: np.ndarray,
) -> tuple[float, tuple[int, int]]:
    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return float(max_val), max_loc


def iter_scales(min_scale: float, max_scale: float, step: float) -> list[float]:
    scales: list[float] = []
    current = min_scale
    while current <= max_scale + (step / 10):
        scales.append(round(current, 4))
        current += step
    return scales


def resize_template(template: np.ndarray, scale: float) -> np.ndarray:
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    width = max(1, int(round(template.shape[1] * scale)))
    height = max(1, int(round(template.shape[0] * scale)))
    return cv2.resize(template, (width, height), interpolation=interpolation)


def find_best_match(
    haystack: np.ndarray,
    template: np.ndarray,
    min_scale: float,
    max_scale: float,
    scale_step: float,
) -> tuple[float, tuple[int, int], tuple[int, int], float]:
    best_score = float("-inf")
    best_loc = (0, 0)
    best_size = (template.shape[1], template.shape[0])
    best_scale = 1.0

    for scale in iter_scales(min_scale, max_scale, scale_step):
        resized = resize_template(template, scale)
        template_height, template_width = resized.shape[:2]
        if template_width > haystack.shape[1] or template_height > haystack.shape[0]:
            continue

        score, top_left = find_match(haystack, resized)
        if score > best_score:
            best_score = score
            best_loc = top_left
            best_size = (template_width, template_height)
            best_scale = scale

    return best_score, best_loc, best_size, best_scale


def count_good_feature_matches(template: np.ndarray, patch: np.ndarray) -> int:
    sift = cv2.SIFT_create()
    template_keypoints, template_descriptors = sift.detectAndCompute(template, None)
    patch_keypoints, patch_descriptors = sift.detectAndCompute(patch, None)

    if template_descriptors is None or patch_descriptors is None:
        return 0

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    matches = matcher.knnMatch(template_descriptors, patch_descriptors, k=2)

    good_matches = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        best, alternate = pair
        if best.distance < 0.75 * alternate.distance:
            good_matches += 1

    return good_matches


def verify_match(
    haystack: np.ndarray,
    template: np.ndarray,
    top_left: tuple[int, int],
    match_size: tuple[int, int],
) -> int:
    x, y = top_left
    width, height = match_size
    patch = haystack[y : y + height, x : x + width]
    if patch.shape[:2] != (height, width):
        return 0

    resized_template = cv2.resize(
        template,
        (width, height),
        interpolation=cv2.INTER_AREA if width < template.shape[1] else cv2.INTER_CUBIC,
    )
    return count_good_feature_matches(resized_template, patch)


def to_pyautogui_coords(
    center_x: float,
    center_y: float,
    screen_width: int,
    screen_height: int,
    capture_width: int,
    capture_height: int,
) -> tuple[int, int]:
    scale_x = screen_width / capture_width
    scale_y = screen_height / capture_height
    return round(center_x * scale_x), round(center_y * scale_y)


def validate_args(args: argparse.Namespace) -> None:
    if args.interval <= 0:
        raise ValueError("--interval must be greater than 0")
    if not 0.0 <= args.threshold <= 1.0:
        raise ValueError("--threshold must be between 0.0 and 1.0")
    if args.min_scale <= 0 or args.max_scale <= 0:
        raise ValueError("--min-scale and --max-scale must be greater than 0")
    if args.min_scale > args.max_scale:
        raise ValueError("--min-scale must be less than or equal to --max-scale")
    if args.scale_step <= 0:
        raise ValueError("--scale-step must be greater than 0")
    if args.min_good_matches < 0:
        raise ValueError("--min-good-matches must be 0 or greater")


def main() -> int:
    args = parse_args()

    try:
        validate_args(args)
        template = load_template(args.template)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    pyautogui.FAILSAFE = True
    screen_width, screen_height = pyautogui.size()
    log(
        "Starting scan loop on the main display "
        f"with interval={args.interval}s threshold={args.threshold:.2f} "
        f"scale_range={args.min_scale:.2f}-{args.max_scale:.2f} "
        f"step={args.scale_step:.2f}"
    )
    if args.dry_run:
        log("Dry-run mode enabled; clicks will be skipped.")

    try:
        with mss.mss() as sct:
            while True:
                try:
                    screenshot, monitor = capture_main_screen(sct)
                except Exception as exc:
                    log(f"Screen capture failed. Check Screen Recording permissions. {exc}")
                    return 1

                score, top_left, match_size, match_scale = find_best_match(
                    haystack=screenshot,
                    template=template,
                    min_scale=args.min_scale,
                    max_scale=args.max_scale,
                    scale_step=args.scale_step,
                )
                if args.verbose:
                    log(
                        f"Best score={score:.4f} scale={match_scale:.2f} "
                        f"size={match_size} at pixel={top_left}"
                    )

                if score >= args.threshold:
                    good_matches = verify_match(
                        haystack=screenshot,
                        template=template,
                        top_left=top_left,
                        match_size=match_size,
                    )
                    if args.verbose:
                        log(f"Feature verification good_matches={good_matches}")
                    if good_matches < args.min_good_matches:
                        time.sleep(args.interval)
                        continue

                    center_x = top_left[0] + (match_size[0] / 2.0)
                    center_y = top_left[1] + (match_size[1] / 2.0)
                    click_x, click_y = to_pyautogui_coords(
                        center_x=center_x,
                        center_y=center_y,
                        screen_width=screen_width,
                        screen_height=screen_height,
                        capture_width=monitor["width"],
                        capture_height=monitor["height"],
                    )
                    log(
                        f"Match score={score:.4f} scale={match_scale:.2f} "
                        f"good_matches={good_matches}; "
                        f"clicking at screen=({click_x}, {click_y}) "
                        f"from capture=({center_x:.1f}, {center_y:.1f})"
                    )
                    if not args.dry_run:
                        try:
                            pyautogui.click(click_x, click_y)
                        except Exception as exc:
                            log(f"Click failed. Check Accessibility permissions. {exc}")
                            return 1

                time.sleep(args.interval)
    except KeyboardInterrupt:
        log("Stopped by user.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
