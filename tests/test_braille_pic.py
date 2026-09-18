"""End-to-end behavior tests for the braille-pic command."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import re

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "braille_pic.py"


class BraillePicCliTests(unittest.TestCase):
    def render(self, image: Image.Image, *arguments: str, width: int = 1) -> str:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.png"
            image.save(source)
            result = subprocess.run(
                [sys.executable, str(COMMAND), str(source), "--width", str(width), *arguments],
                capture_output=True,
                check=True,
                cwd=ROOT,
                text=True,
            )
        return result.stdout

    def test_renders_dark_pixels_at_their_unicode_braille_dot_positions(self) -> None:
        image = Image.new("L", (2, 4), color=255)
        image.putpixel((0, 0), 0)  # dot 1
        image.putpixel((1, 2), 0)  # dot 6

        self.assertEqual(self.render(image, "--no-color"), "\u2821\n")

    def test_each_source_pixel_maps_to_its_standard_braille_dot(self) -> None:
        expected_masks = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))
        for x in range(2):
            for y in range(4):
                with self.subTest(x=x, y=y):
                    image = Image.new("L", (2, 4), color=255)
                    image.putpixel((x, y), 0)
                    self.assertEqual(
                        self.render(image, "--no-color"),
                        chr(0x2800 + expected_masks[x][y]) + "\n",
                    )

    def test_invert_switches_light_pixels_on(self) -> None:
        image = Image.new("L", (2, 4), color=255)

        self.assertEqual(self.render(image, "--invert", "--no-color"), "\u28ff\n")

    def test_width_sets_the_number_of_braille_columns(self) -> None:
        image = Image.new("L", (4, 4), color=255)

        self.assertEqual(self.render(image, "--no-color", width=2), "\u2800\u2800\n")

    def test_colours_each_braille_cell_with_its_average_rgb_value(self) -> None:
        image = Image.new("RGB", (2, 4), color=(12, 34, 56))

        self.assertEqual(self.render(image), "\x1b[38;2;12;34;56m\u28ff\x1b[0m\n")

    def test_dither_turns_a_midtone_into_a_repeatable_braille_shading_pattern(self) -> None:
        image = Image.new("L", (2, 4), color=128)

        self.assertEqual(self.render(image, "--dither", "--no-color"), "\u286a\n")

    def test_contrast_can_separate_nearby_tones_into_different_dot_values(self) -> None:
        image = Image.new("L", (2, 4), color=127)
        for y in range(4):
            image.putpixel((0, y), 120)

        self.assertEqual(self.render(image, "--contrast", "2", "--no-color"), "\u2847\n")

    def test_background_adds_an_ansi_background_colour(self) -> None:
        image = Image.new("RGB", (2, 4), color=(12, 34, 56))

        self.assertEqual(
            self.render(image, "--background", "96,96,96"),
            "\x1b[48;2;96;96;96m\x1b[38;2;12;34;56m\u28ff\x1b[0m\n",
        )

    def test_background_adjusts_nearby_character_colours_for_legibility(self) -> None:
        image = Image.new("RGB", (2, 4), color=(110, 110, 110))

        output = self.render(image, "--background", "96,96,96")
        match = re.search(r"\x1b\[38;2;(\d+);(\d+);(\d+)m", output)
        self.assertIsNotNone(match)
        foreground = tuple(int(component) for component in match.groups())
        self.assertGreaterEqual(self.contrast_ratio(foreground, (96, 96, 96)), 2.0)

    def test_background_makes_white_characters_visible_on_white(self) -> None:
        image = Image.new("RGB", (2, 4), color=(255, 255, 255))

        output = self.render(image, "--background", "255,255,255")
        match = re.search(r"\x1b\[38;2;(\d+);(\d+);(\d+)m", output)
        self.assertIsNotNone(match)
        foreground = tuple(int(component) for component in match.groups())
        self.assertGreaterEqual(self.contrast_ratio(foreground, (255, 255, 255)), 2.0)

    def test_saturation_enhances_colour_without_changing_the_output_format(self) -> None:
        image = Image.new("RGB", (2, 4), color=(100, 120, 140))

        output = self.render(image, "--saturation", "1.5")
        match = re.search(r"\x1b\[38;2;(\d+);(\d+);(\d+)m", output)
        self.assertIsNotNone(match)
        foreground = tuple(int(component) for component in match.groups())
        self.assertGreater(max(foreground) - min(foreground), 40)

    def test_auto_background_uses_a_neutral_grey_from_the_source_image(self) -> None:
        image = Image.new("RGB", (2, 4), color=(180, 174, 168))

        output = self.render(image, "--background", "auto")
        self.assertTrue(output.startswith("\x1b[48;2;174;174;174m"))

    @staticmethod
    def contrast_ratio(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
        def luminance(color: tuple[int, int, int]) -> float:
            channels = []
            for component in color:
                normalized = component / 255
                channels.append(
                    normalized / 12.92
                    if normalized <= 0.04045
                    else ((normalized + 0.055) / 1.055) ** 2.4
                )
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

        brighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
        return (brighter + 0.05) / (darker + 0.05)


if __name__ == "__main__":
    unittest.main()
