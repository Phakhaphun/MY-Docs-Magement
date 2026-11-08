"""Noninteractive Matplotlib rendering, shared by desktop preview and CLI export."""

from io import BytesIO
from threading import RLock

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties

from .spatial import spatial_grid, method_name
from .settings import validate_settings

COLORS = ["#203E9A", "#19A9DF", "#35BD89", "#F1D948", "#F08A38", "#C82E3C"]
RENDER_LOCK = RLock()


def thermal_palette() -> LinearSegmentedColormap:
    """Continuous RGB ramp; 256 entries place all six anchors exactly on the LUT."""
    return LinearSegmentedColormap.from_list("six_anchor_thermal", COLORS, N=256)


def render_png(settings: dict, *, preview: bool = False) -> bytes:
    """Render PNG bytes without opening a window or modifying measurements."""
    settings = validate_settings(settings)
    grid = spatial_grid(settings)
    width, height = settings["area_width"], settings["area_height"]
    with RENDER_LOCK:
        figure = Figure(figsize=(settings["figure_width"], settings["figure_height"]),
                        dpi=110 if preview else settings["dpi"], facecolor="white")
        FigureCanvasAgg(figure)
        try:
            axes = figure.add_subplot(111)
            palette = thermal_palette().with_extremes(bad="#edf2f7")
            image = axes.imshow(grid, origin="upper", extent=(0, width, height, 0), aspect="auto",
                                interpolation="bilinear", interpolation_stage="rgba", cmap=palette,
                                norm=Normalize(settings["color_min"], settings["color_max"], clip=True))
            axes.set_box_aspect(height / width)
            axes.set_xlim(-0.035 * width, 1.035 * width)
            axes.set_ylim(1.05 * height, -0.05 * height)
            axes.set_xticks(np.linspace(0, width, 5))
            axes.set_yticks(np.linspace(0, height, 5))
            font = FontProperties(family=["Tahoma", "DejaVu Sans"])
            axes.set_xlabel(settings["x_axis_title"].strip(), labelpad=10, fontproperties=font)
            axes.set_ylabel(settings["y_axis_title"].strip(), labelpad=10, fontproperties=font)
            axes.set_title(settings["title"], fontsize=15, pad=20, color="#18324d", wrap=True, fontproperties=font)
            for index, (x, y) in enumerate(settings["sensor_positions"]):
                if settings["show_sensor_markers"]:
                    axes.plot(x, y, "o", ms=6, mfc="white", mec="#18324d", mew=1.3, zorder=3)
                if settings["show_sensor_labels"]:
                    right = x > width * .75
                    lower = y > height * .5
                    axes.annotate(f"{settings['sensor_names'][index]}  {np.asarray(settings['temperatures']).ravel()[index]:.2f} °C",
                                  (x, y), xytext=(-8 if right else 8, 10 if lower else -10),
                                  textcoords="offset points", fontsize=9, color="#18324d", fontproperties=font,
                                  ha="right" if right else "left", va="bottom" if lower else "top",
                                  bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#dee8f2", alpha=.94))
            bar = figure.colorbar(image, ax=axes, pad=.035, shrink=.83,
                                 ticks=np.linspace(settings["color_min"], settings["color_max"], 6))
            bar.set_label("Temperature (°C)", labelpad=12)
            if settings["estimation_method"] == "idw":
                figure.text(.5, .015, f"Estimated field · {method_name(settings)} · Markers are measured values",
                            ha="center", fontsize=8, color="#647c94", fontproperties=font)
            elif settings["estimation_method"] == "smooth":
                figure.text(.5,.015,"Smooth cubic · Measured region only · Markers are measured values",
                            ha="center",fontsize=8,color="#647c94",fontproperties=font)
            figure.subplots_adjust(left=.10, right=.88, bottom=.12, top=.88)
            buffer = BytesIO()
            figure.savefig(buffer, format="png", bbox_inches="tight", metadata={"Software": "Temperature Heatmap Generator"})
            return buffer.getvalue()
        finally:
            figure.clear()
