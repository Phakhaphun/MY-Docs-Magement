"""Generate a PNG from JSON configuration without launching the desktop UI."""

import argparse
from pathlib import Path

from heatmap.plotting import render_png
from heatmap.settings import CONFIG_PATH, load_settings, output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a temperature heatmap PNG")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        image = render_png(settings)
        path = output_path(settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image)
        values = sum(settings["temperatures"], [])
        print(f"Saved PNG: {path}")
        print(f"Interpolation grid: {settings['grid_rows']} x {settings['grid_cols']}")
        print(f"Measured temperature range: {min(values):.2f} - {max(values):.2f} C")
        print(f"Display color range: {settings['color_min']:.2f} - {settings['color_max']:.2f} C")
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
