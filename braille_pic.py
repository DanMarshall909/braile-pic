#!/usr/bin/env python3
"""Render an image as Unicode Braille art."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageEnhance


# Unicode Braille dot numbering, indexed as (x, y) within a 2 × 4 cell.
DOT_MASKS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
BRAILLE_BASE = 0x2800


def parse_rgb(value: str) -> tuple[int, int, int]:
    """Parse a comma-separated ANSI true-color value."""
    try:
        red, green, blue = (int(component) for component in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be three comma-separated integers") from error
    if not all(0 <= component <= 255 for component in (red, green, blue)):
        raise argparse.ArgumentTypeError("each RGB component must be between 0 and 255")
    return red, green, blue


def parse_background(value: str) -> tuple[int, int, int] | str:
    """Accept an explicit RGB background or derive one from the source image."""
    if value.lower() == "auto":
        return "auto"
    return parse_rgb(value)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert an image to Unicode Braille dot-matrix art."
    )
    parser.add_argument("image", type=Path, help="path to the source image")
    parser.add_argument(
        "--width",
        type=int,
        default=80,
        help="output width in Braille characters (default: 80)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=128,
        help="grayscale values below this activate a dot (0–255; default: 128)",
    )
    parser.add_argument(
        "--invert",
        action="store_true",
        help="activate light pixels instead of dark pixels",
    )
    parser.add_argument(
        "--no-color",
        action="store_false",
        dest="color",
        help="omit ANSI true-color escape sequences",
    )
    parser.add_argument(
        "--dither",
        action="store_true",
        help="use Floyd–Steinberg dithering to preserve midtone shading",
    )
    parser.add_argument(
        "--contrast",
        type=float,
        default=1.0,
        help="contrast multiplier; 1 preserves the source (default: 1)",
    )
    parser.add_argument(
        "--background",
        type=parse_background,
        metavar="R,G,B|auto",
        help="ANSI background RGB or auto for a neutral source-derived grey",
    )
    parser.add_argument(
        "--saturation",
        type=float,
        default=1.0,
        help="color saturation multiplier; 1 preserves the source (default: 1)",
    )
    parser.add_argument(
        "--adaptive-colours",
        action="store_true",
        help="derive foreground and background colors separately for each Braille cell",
    )
    arguments = parser.parse_args()
    if arguments.width < 1:
        parser.error("--width must be at least 1")
    if not 0 <= arguments.threshold <= 255:
        parser.error("--threshold must be between 0 and 255")
    if arguments.contrast <= 0:
        parser.error("--contrast must be greater than 0")
    if arguments.saturation < 0:
        parser.error("--saturation must not be negative")
    return arguments


def resize_for_braille(image: Image.Image, width: int) -> Image.Image:
    """Resize an image to a whole number of 2 × 4 Braille cells."""
    dot_width = width * 2
    proportional_height = image.height * dot_width / image.width
    dot_height = max(4, math.ceil(proportional_height / 4) * 4)
    return image.convert("RGB").resize((dot_width, dot_height), Image.Resampling.LANCZOS)


def brightness(color: tuple[int, int, int]) -> int:
    """Return a perceptual grayscale brightness for an RGB color."""
    red, green, blue = color
    return round(0.299 * red + 0.587 * green + 0.114 * blue)


def average_color(pixels: Image.Image, left: int, top: int) -> tuple[int, int, int]:
    """Return the mean RGB value of one 2 × 4 Braille cell."""
    channels = [0, 0, 0]
    for x in range(2):
        for y in range(4):
            for channel, value in enumerate(pixels.getpixel((left + x, top + y))):
                channels[channel] += value
    return tuple(value // 8 for value in channels)


def average_colors(colors: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    """Return the mean RGB value of a non-empty color collection."""
    return tuple(sum(color[channel] for color in colors) // len(colors) for channel in range(3))


def relative_luminance(color: tuple[int, int, int]) -> float:
    """Return the WCAG relative luminance of an sRGB color."""
    channels = []
    for component in color:
        normalized = component / 255
        channels.append(
            normalized / 12.92
            if normalized <= 0.04045
            else ((normalized + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    """Return the WCAG contrast ratio between two sRGB colors."""
    brighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (brighter + 0.05) / (darker + 0.05)


def blend(
    color: tuple[int, int, int], target: tuple[int, int, int], amount: float
) -> tuple[int, int, int]:
    """Blend an RGB color toward a target while retaining its hue as far as possible."""
    return tuple(round(source + (destination - source) * amount) for source, destination in zip(color, target))


def estimate_background(image: Image.Image) -> tuple[int, int, int]:
    """Estimate a neutral background from the upper corners of a portrait-like image."""
    pixels = image.convert("RGB")
    sample_width = max(1, pixels.width // 5)
    sample_height = max(1, pixels.height // 5)
    samples = [
        pixels.getpixel((x, y))
        for y in range(sample_height)
        for x in (*range(sample_width), *range(pixels.width - sample_width, pixels.width))
    ]
    neutral_value = round(sum(sum(color) for color in samples) / (len(samples) * 3))
    return neutral_value, neutral_value, neutral_value


def ensure_contrast(
    foreground: tuple[int, int, int], background: tuple[int, int, int], minimum: float = 2.0
) -> tuple[int, int, int]:
    """Adjust a foreground color only when it is too close to its background."""
    if contrast_ratio(foreground, background) >= minimum:
        return foreground

    candidates: list[tuple[float, tuple[int, int, int]]] = []
    for target in ((0, 0, 0), (255, 255, 255)):
        if contrast_ratio(target, background) < minimum:
            continue
        low, high = 0.0, 1.0
        for _ in range(16):
            amount = (low + high) / 2
            if contrast_ratio(blend(foreground, target, amount), background) >= minimum:
                high = amount
            else:
                low = amount

        adjusted = blend(foreground, target, high)
        while contrast_ratio(adjusted, background) < minimum and adjusted != target:
            adjusted = tuple(
                component + (1 if destination > component else -1 if destination < component else 0)
                for component, destination in zip(adjusted, target)
            )
        candidates.append((high, adjusted))

    return min(candidates, key=lambda candidate: candidate[0])[1]


def dither(pixels: Image.Image, threshold: int) -> list[list[bool]]:
    """Convert RGB pixels to a deterministic black-and-white dither pattern."""
    values = [
        [brightness(pixels.getpixel((x, y))) for x in range(pixels.width)]
        for y in range(pixels.height)
    ]
    dots = [[False] * pixels.width for _ in range(pixels.height)]
    for y in range(pixels.height):
        for x in range(pixels.width):
            old_value = values[y][x]
            is_dark = old_value < threshold
            dots[y][x] = is_dark
            new_value = 0 if is_dark else 255
            error = old_value - new_value
            if x + 1 < pixels.width:
                values[y][x + 1] += error * 7 / 16
            if y + 1 < pixels.height:
                if x > 0:
                    values[y + 1][x - 1] += error * 3 / 16
                values[y + 1][x] += error * 5 / 16
                if x + 1 < pixels.width:
                    values[y + 1][x + 1] += error / 16
    return dots


def render(
    image: Image.Image,
    width: int,
    threshold: int,
    invert: bool,
    color: bool,
    dithered: bool,
    contrast: float,
    background: tuple[int, int, int] | None,
    saturation: float,
    adaptive_colours: bool,
) -> str:
    """Return the image as lines of Unicode Braille characters."""
    enhanced = ImageEnhance.Color(image).enhance(saturation)
    pixels = resize_for_braille(ImageEnhance.Contrast(enhanced).enhance(contrast), width)
    dithered_dots = dither(pixels, threshold) if dithered else None
    lines: list[str] = []
    for top in range(0, pixels.height, 4):
        line: list[str] = []
        for left in range(0, pixels.width, 2):
            pattern = 0
            lit_colors: list[tuple[int, int, int]] = []
            unlit_colors: list[tuple[int, int, int]] = []
            for x in range(2):
                for y in range(4):
                    is_dark = (
                        dithered_dots[top + y][left + x]
                        if dithered_dots is not None
                        else brightness(pixels.getpixel((left + x, top + y))) < threshold
                    )
                    is_lit = is_dark != invert
                    pixel_color = pixels.getpixel((left + x, top + y))
                    if is_lit:
                        pattern |= DOT_MASKS[x][y]
                        lit_colors.append(pixel_color)
                    else:
                        unlit_colors.append(pixel_color)
            character = chr(BRAILLE_BASE + pattern)
            if color:
                if adaptive_colours:
                    fallback = average_color(pixels, left, top)
                    foreground = average_colors(lit_colors) if lit_colors else fallback
                    cell_background = average_colors(unlit_colors) if unlit_colors else fallback
                    red, green, blue = ensure_contrast(foreground, cell_background)
                    background_red, background_green, background_blue = cell_background
                    line.append(
                        f"\x1b[48;2;{background_red};{background_green};{background_blue}m"
                        f"\x1b[38;2;{red};{green};{blue}m{character}"
                    )
                else:
                    red, green, blue = average_color(pixels, left, top)
                    if background is not None:
                        red, green, blue = ensure_contrast((red, green, blue), background)
                    line.append(f"\x1b[38;2;{red};{green};{blue}m{character}")
            else:
                line.append(character)
        background_prefix = ""
        if color and background is not None and not adaptive_colours:
            red, green, blue = background
            background_prefix = f"\x1b[48;2;{red};{green};{blue}m"
        lines.append(background_prefix + "".join(line) + ("\x1b[0m" if color else ""))
    return "\n".join(lines)


def main() -> int:
    arguments = parse_arguments()
    try:
        with Image.open(arguments.image) as image:
            background = (
                estimate_background(image)
                if arguments.background == "auto"
                else arguments.background
            )
            print(
                render(
                    image,
                    arguments.width,
                    arguments.threshold,
                    arguments.invert,
                    arguments.color,
                    arguments.dither,
                    arguments.contrast,
                    background,
                    arguments.saturation,
                    arguments.adaptive_colours,
                )
            )
    except (OSError, ValueError) as error:
        print(f"braille-pic: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
