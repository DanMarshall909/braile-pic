# braille-pic

Turn an image into terminal-friendly Unicode Braille dot art. Each output
character represents a 2 × 4 dot-matrix cell, so it holds eight source pixels.
The output uses ANSI 24-bit foreground colours based on each cell's average RGB
value.

## Requirements

- Python 3.10+
- [Pillow](https://python-pillow.org/)

## Usage

```bash
python3 braille_pic.py photo.png --width 100
```

Useful options:

- `--width 80` sets the output width in Braille characters.
- `--threshold 128` treats grayscale values below the threshold as active dots.
- `--invert` activates light pixels instead, useful for dark source images.
- `--no-color` disables ANSI colour codes for plain-text files or unsupported terminals.
- `--dither` uses Floyd–Steinberg dithering, giving gradients a dot-pattern shading effect.
- `--contrast 2` increases contrast before rendering; `1` preserves the source.
- `--background 96,96,96` applies a true-color terminal background; use `auto` to
  derive a neutral grey from the image's upper corners.
- `--saturation 1.2` gently enriches color while preserving natural skin tones.
- `--adaptive-colours` assigns a separate foreground and background color to each
  Braille cell for the closest color approximation.

Pipe or save the result as normal terminal text:

```bash
python3 braille_pic.py photo.png --width 100 > photo.txt
```
