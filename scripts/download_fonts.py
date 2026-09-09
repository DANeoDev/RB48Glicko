"""Download Google Fonts locally for offline and GDPR-compliant self-hosting."""

from pathlib import Path
import re
import urllib.request

FONTS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)
CSS_OUTPUT = Path(__file__).resolve().parents[1] / "web" / "static" / "fonts.css"

URL = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700&"
    "family=Bangers&"
    "family=Caveat:wght@600;700&"
    "family=Courier+Prime:wght@700&"
    "family=Creepster&"
    "family=Great+Vibes&"
    "family=Orbitron:wght@700;900&"
    "family=Permanent+Marker&"
    "family=Playfair+Display:ital,wght@1,700&"
    "family=Press+Start+2P&"
    "family=Rye&display=swap"
)


def main():
    req = urllib.request.Request(
        URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        },
    )
    raw_css = urllib.request.urlopen(req).read().decode("utf-8")

    # Split by @font-face
    blocks = raw_css.split("@font-face")
    local_blocks = []
    downloaded = 0

    for idx, b in enumerate(blocks):
        if not b.strip():
            continue

        match = re.search(r"url\((https://fonts\.gstatic\.com/s/[^\)]+)\)", b)
        if not match:
            continue
        font_url = match.group(1)

        # Parse family, weight, style
        fam_m = re.search(r"font-family:\s*['\"]?([^'\";]+)['\"]?", b)
        weight_m = re.search(r"font-weight:\s*([^'\";]+);", b)
        style_m = re.search(r"font-style:\s*([^'\";]+);", b)

        family = fam_m.group(1).replace(" ", "_").replace("'", "").replace('"', "") if fam_m else "font"
        weight = weight_m.group(1).strip() if weight_m else "400"
        style = style_m.group(1).strip() if style_m else "normal"

        subset = "latin"
        if "/* latin-ext */" in b:
            subset = "latin-ext"
        elif "/* cyrillic */" in b or "/* vietnamese */" in b or "/* greek */" in b or "/* cyrillic-ext */" in b or "/* greek-ext */" in b:
            continue

        filename = f"{family}_{weight}_{style}_{subset}_{downloaded}.woff2".lower()
        local_path = FONTS_DIR / filename

        print(f"Downloading {filename}...")
        font_data = urllib.request.urlopen(font_url).read()
        with open(local_path, "wb") as f:
            f.write(font_data)

        # Replace remote URL with relative path for CSS (relative to static/fonts.css -> fonts/filename)
        clean_block = b.replace(font_url, f"fonts/{filename}")
        local_blocks.append("@font-face" + clean_block)
        downloaded += 1

    with open(CSS_OUTPUT, "w", encoding="utf-8") as f:
        f.write("\n".join(local_blocks))

    print(f"Done! Downloaded {downloaded} font files into {FONTS_DIR} and created {CSS_OUTPUT}")


if __name__ == "__main__":
    main()
