#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import mss
import pyautogui

from auto_accept import (
    capture_main_screen,
    find_best_match,
    load_template,
    log,
    to_pyautogui_coords,
    verify_match,
)


DEFAULT_TEMPLATE = Path(__file__).with_name("xcode_build_button.png")
DEFAULT_DARK_TEMPLATE = Path(__file__).with_name("xcode_build_controls_dark.png")
DEFAULT_WARNING_SOUND = Path("/System/Library/Sounds/Glass.aiff")


@dataclass(frozen=True)
class TemplateSpec:
    path: Path
    click_x_ratio: float = 0.5
    click_y_ratio: float = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search the main display exactly once for a template and click the best match."
        )
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=DEFAULT_TEMPLATE,
        help="Path to the primary template image. Dark-mode fallback is searched as well.",
    )
    parser.add_argument(
        "--app-name",
        default="",
        help="Optional application name to activate before scanning.",
    )
    parser.add_argument(
        "--warning-seconds",
        type=float,
        default=5.0,
        help="Seconds to show the takeover warning before activating and clicking.",
    )
    parser.add_argument(
        "--warning-sound",
        type=Path,
        default=DEFAULT_WARNING_SOUND,
        help="Sound file to loop during the warning phase.",
    )
    parser.add_argument(
        "--mouse-abort-threshold",
        type=int,
        default=4,
        help="Abort if the mouse moves by at least this many pixels during the warning.",
    )
    parser.add_argument(
        "--settle-time",
        type=float,
        default=1.0,
        help="Seconds to wait after activating the app.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.80,
        help="Normalized template matching threshold from 0.0 to 1.0.",
    )
    parser.add_argument(
        "--min-scale",
        type=float,
        default=0.50,
        help="Smallest scale factor to test for the template.",
    )
    parser.add_argument(
        "--max-scale",
        type=float,
        default=1.50,
        help="Largest scale factor to test for the template.",
    )
    parser.add_argument(
        "--scale-step",
        type=float,
        default=0.05,
        help="Increment between tested template scales.",
    )
    parser.add_argument(
        "--min-good-matches",
        type=int,
        default=0,
        help="Minimum SIFT good matches required before clicking.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect the match without clicking.",
    )
    parser.add_argument(
        "--move-duration",
        type=float,
        default=0.20,
        help="Seconds used to move the mouse to the target before clicking.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed match information.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.warning_seconds < 0:
        raise ValueError("--warning-seconds must be 0 or greater")
    if args.mouse_abort_threshold < 0:
        raise ValueError("--mouse-abort-threshold must be 0 or greater")
    if args.settle_time < 0:
        raise ValueError("--settle-time must be 0 or greater")
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
    if args.move_duration < 0:
        raise ValueError("--move-duration must be 0 or greater")


def activate_app(app_name: str) -> None:
    script = f'tell application "{app_name}" to activate'
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def load_templates(primary_template: Path) -> list[tuple[TemplateSpec, object]]:
    templates: list[tuple[TemplateSpec, object]] = []
    seen_paths: set[Path] = set()
    specs = [
        TemplateSpec(path=primary_template, click_x_ratio=0.5, click_y_ratio=0.5),
        TemplateSpec(path=DEFAULT_DARK_TEMPLATE, click_x_ratio=0.78, click_y_ratio=0.5),
    ]
    for spec in specs:
        resolved = spec.path.resolve()
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        loaded = load_template(spec.path)
        templates.append((TemplateSpec(resolved, spec.click_x_ratio, spec.click_y_ratio), loaded))
    return templates


def get_frontmost_app() -> str:
    script = (
        'tell application "System Events" to get name of first application process '
        "whose frontmost is true"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def pulse_style(elapsed: float) -> tuple[str, float]:
    phase = (math.sin(elapsed * math.tau * 2.2) + 1.0) / 2.0
    phase = phase**0.55
    red = 255
    green = int(16 + (239 * phase))
    blue = int(8 + (82 * (phase**1.4)))
    alpha = 0.48 + (0.50 * phase)
    return f"#{red:02x}{green:02x}{blue:02x}", alpha


def geometry(width: int, height: int, left: int, top: int) -> str:
    return f"{width}x{height}{left:+d}{top:+d}"


def start_warning_sound(sound_path: Path) -> subprocess.Popen[str] | None:
    if not sound_path.is_file():
        log(f"Warning sound not found, continuing silently: {sound_path}")
        return None

    cmd = (
        f"while true; do afplay {shlex.quote(str(sound_path))}; done"
    )
    return subprocess.Popen(
        ["/bin/zsh", "-lc", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        text=True,
    )


def stop_warning_sound(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=1.0)


def mouse_moved(
    start_x: int,
    start_y: int,
    current_x: int,
    current_y: int,
    threshold: int,
) -> bool:
    return abs(current_x - start_x) >= threshold or abs(current_y - start_y) >= threshold


def show_takeover_warning(seconds: float, sound_path: Path, abort_threshold: int) -> bool:
    if seconds <= 0:
        return True

    import tkinter as tk

    with mss.mss() as sct:
        monitors = [dict(monitor) for monitor in sct.monitors[1:]]

    root = tk.Tk()
    root.withdraw()
    border_frames: list[tk.Frame] = []
    border_windows: list[tk.Toplevel] = []
    thickness = 28
    sound_process: subprocess.Popen[str] | None = None
    result = True

    try:
        for monitor in monitors:
            left = monitor["left"]
            top = monitor["top"]
            width = monitor["width"]
            height = monitor["height"]

            window_specs = [
                (width, thickness, left, top),
                (width, thickness, left, top + height - thickness),
                (thickness, height, left, top),
                (thickness, height, left + width - thickness, top),
            ]
            for spec_width, spec_height, spec_left, spec_top in window_specs:
                window = tk.Toplevel(root)
                window.overrideredirect(True)
                window.attributes("-topmost", True)
                try:
                    window.attributes("-alpha", 0.90)
                except tk.TclError:
                    pass
                frame = tk.Frame(window, bg="#ff3300", highlightthickness=0, bd=0)
                frame.pack(fill="both", expand=True)
                window.geometry(geometry(spec_width, spec_height, spec_left, spec_top))
                border_windows.append(window)
                border_frames.append(frame)

        start_x, start_y = pyautogui.position()
        sound_process = start_warning_sound(sound_path)
        start_time = time.monotonic()
        log(
            f"Takeover warning for {seconds:.1f}s. Move the mouse to cancel."
        )

        def finish(next_result: bool) -> None:
            nonlocal result
            result = next_result
            root.quit()

        def tick() -> None:
            elapsed = time.monotonic() - start_time
            if elapsed >= seconds:
                finish(True)
                return

            current_x, current_y = pyautogui.position()
            if mouse_moved(start_x, start_y, current_x, current_y, abort_threshold):
                log("Aborted because the mouse moved during the warning phase.")
                finish(False)
                return

            color, alpha = pulse_style(elapsed)
            for window, frame in zip(border_windows, border_frames):
                window.configure(bg=color)
                frame.configure(bg=color)
                try:
                    window.attributes("-alpha", alpha)
                except tk.TclError:
                    pass
            root.after(20, tick)

        root.after(0, tick)
        root.mainloop()
        return result
    finally:
        stop_warning_sound(sound_process)
        for window in border_windows:
            try:
                window.destroy()
            except tk.TclError:
                pass
        try:
            root.destroy()
        except Exception:
            pass


def main() -> int:
    args = parse_args()

    try:
        validate_args(args)
        templates = load_templates(args.template)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    pyautogui.FAILSAFE = True
    screen_width, screen_height = pyautogui.size()
    previous_app = ""
    result = 1

    try:
        previous_app = get_frontmost_app()
        if previous_app:
            log(f"Remembering frontmost app: {previous_app}")

        if not show_takeover_warning(
            seconds=args.warning_seconds,
            sound_path=args.warning_sound,
            abort_threshold=args.mouse_abort_threshold,
        ):
            result = 1
        else:
            if args.app_name:
                log(f"Activating {args.app_name}.")
                activate_app(args.app_name)
                if args.settle_time:
                    time.sleep(args.settle_time)

            template_names = ", ".join(spec.path.name for spec, _ in templates)
            log(
                f"Searching once for [{template_names}] with threshold={args.threshold:.2f} "
                f"scale_range={args.min_scale:.2f}-{args.max_scale:.2f} step={args.scale_step:.2f}"
            )

            try:
                with mss.mss() as sct:
                    screenshot, monitor = capture_main_screen(sct)
            except Exception as exc:
                log(f"Screen capture failed. Check Screen Recording permissions. {exc}")
                result = 1
            else:
                best_spec = None
                best_template = None
                score = float("-inf")
                top_left = (0, 0)
                match_size = (0, 0)
                match_scale = 1.0

                for template_spec, template_image in templates:
                    current_score, current_top_left, current_match_size, current_match_scale = (
                        find_best_match(
                            haystack=screenshot,
                            template=template_image,
                            min_scale=args.min_scale,
                            max_scale=args.max_scale,
                            scale_step=args.scale_step,
                        )
                    )
                    if args.verbose:
                        log(
                            f"Template {template_spec.path.name}: score={current_score:.4f} "
                            f"scale={current_match_scale:.2f} size={current_match_size} "
                            f"at pixel={current_top_left}"
                        )
                    if current_score > score:
                        score = current_score
                        top_left = current_top_left
                        match_size = current_match_size
                        match_scale = current_match_scale
                        best_spec = template_spec
                        best_template = template_image

                if best_spec is None or best_template is None:
                    log("No templates available for matching.")
                    result = 1
                else:
                    if args.verbose:
                        log(
                            f"Selected template {best_spec.path.name}: score={score:.4f} "
                            f"scale={match_scale:.2f} size={match_size} at pixel={top_left}"
                        )

                    if score < args.threshold:
                        log(f"No match above threshold. Best score was {score:.4f}.")
                        result = 1
                    else:
                        good_matches = verify_match(
                            haystack=screenshot,
                            template=best_template,
                            top_left=top_left,
                            match_size=match_size,
                        )
                        if args.verbose:
                            log(f"Feature verification good_matches={good_matches}")

                        if good_matches < args.min_good_matches:
                            log(
                                f"Rejected match with score={score:.4f}; only {good_matches} "
                                f"feature matches, need {args.min_good_matches}."
                            )
                            result = 1
                        else:
                            center_x = top_left[0] + (match_size[0] * best_spec.click_x_ratio)
                            center_y = top_left[1] + (match_size[1] * best_spec.click_y_ratio)
                            click_x, click_y = to_pyautogui_coords(
                                center_x=center_x,
                                center_y=center_y,
                                screen_width=screen_width,
                                screen_height=screen_height,
                                capture_width=monitor["width"],
                                capture_height=monitor["height"],
                            )
                            log(
                                f"Match template={best_spec.path.name} score={score:.4f} "
                                f"scale={match_scale:.2f} good_matches={good_matches}; "
                                f"target screen=({click_x}, {click_y})"
                            )

                            if args.dry_run:
                                log("Dry-run mode enabled; skipping click.")
                                result = 0
                            else:
                                try:
                                    pyautogui.moveTo(click_x, click_y, duration=args.move_duration)
                                    pyautogui.click(click_x, click_y)
                                except Exception as exc:
                                    log(f"Click failed. Check Accessibility permissions. {exc}")
                                    result = 1
                                else:
                                    log("Click completed.")
                                    result = 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        result = 1
    finally:
        if previous_app and previous_app != args.app_name:
            try:
                log(f"Restoring frontmost app: {previous_app}")
                activate_app(previous_app)
            except Exception as exc:
                log(f"Failed to restore {previous_app}: {exc}")
                result = 1

    return result


if __name__ == "__main__":
    raise SystemExit(main())
