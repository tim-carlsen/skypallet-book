import pathlib

# Paths relative to INNER project directory (the one with quicklooks, scripts, etc.)
ROOT = pathlib.Path(__file__).resolve().parents[1]  # skypallet-book (inner)
ARCHIVE_DIR = ROOT / "quicklooks" / "archive"
ARCHIVE_MD = ROOT / "archive.md"


def list_quicklook_dates():
    """Return sorted list of YYYYMMDD strings from quicklooks/archive/*_skypallet_quicklook.png."""
    dates = []
    for png in ARCHIVE_DIR.glob("*_skypallet_quicklook.png"):
        name = png.name  # e.g. 20260906_skypallet_quicklook.png
        date_str = name.split("_")[0]  # "20260906"
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)
    return sorted(set(dates))


def make_options_html(dates):
    """Return the <option> HTML lines for the dropdown, marking the last date as selected."""
    lines = []
    default = dates[-1] if dates else None
    for d in dates:
        # format YYYYMMDD -> YYYY-MM-DD for display
        label = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        selected = " selected" if d == default else ""
        lines.append(f'    <option value="{d}"{selected}>{label}</option>')
    return "\n".join(lines)


def main():
    dates = list_quicklook_dates()
    options_html = make_options_html(dates) if dates else ""

    # Default image: last date if any, else empty
    default_src = f"{dates[-1]}_skypallet_quicklook.png" if dates else ""

    # NOTE: use triple quotes and include the MyST raw HTML block
    content = (
        "# Archive\n\n"
        "Select a date to view the archived quicklook.\n\n"
        "```{raw} html\n"
        "<div>\n"
        "  <label for=\"ql-date\">Date:</label>\n"
        "  <select id=\"ql-date\" onchange=\"updateQuicklook()\">\n"
        f"{options_html}\n"
        "  </select>\n"
        "</div>\n\n"
        "<div style=\"margin-top: 1em;\">\n"
        "  <img id=\"ql-image\"\n"
        f"       src=\"quicklooks/archive/{default_src}\"\n"
        "       style=\"width: 100%; border: 1px solid #ccc;\"\n"
        "       alt=\"Skypallet quicklook\" />\n"
        "</div>\n\n"
        "<script>\n"
        "function updateQuicklook() {\n"
        "  const select = document.getElementById('ql-date');\n"
        "  const dateVal = select.value; // YYYYMMDD\n"
        "  const img = document.getElementById('ql-image');\n"
        "  img.src = 'quicklooks/archive/' + dateVal + '_skypallet_quicklook.png';\n"
        "}\n"
        "</script>\n"
        "```\n"
    )

    ARCHIVE_MD.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
