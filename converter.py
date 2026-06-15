from flask import Flask, request, send_file, jsonify
from PIL import Image
import io
import os

app = Flask(__name__)

SUPPORTED_FORMATS = {"png", "jpg", "jpeg", "webp"}

FORMAT_MAP = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}

MIME_MAP = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

SAVE_OPTIONS = {
    "JPEG": {"quality": 95},
    "WEBP": {"quality": 95},
    "PNG": {"optimize": True},
}


def _normalize(fmt: str) -> str:
    return fmt.lower().strip().lstrip(".")


def _validate_format(fmt: str):
    fmt = _normalize(fmt)
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{fmt}'. Supported: {sorted(SUPPORTED_FORMATS)}"
        )
    return fmt


def _has_transparency(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        alpha = img.getchannel("A")
        return alpha.getextrema()[0] < 255
    if img.mode == "P":
        if "transparency" in img.info:
            return True
        try:
            rgba = img.convert("RGBA")
            alpha = rgba.getchannel("A")
            return alpha.getextrema()[0] < 255
        except Exception:
            return False
    return False


def _flatten_white_background(img: Image.Image) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bg = Image.new("RGB", img.size, (255, 255, 255))
    r, g, b, a = img.split()
    bg.paste(Image.merge("RGB", (r, g, b)), mask=a)
    return bg


def convert_image(input_bytes: bytes, output_format: str, quality: int = 95) -> bytes:
    img = Image.open(io.BytesIO(input_bytes))

    pillow_format = FORMAT_MAP[output_format]

    if pillow_format == "JPEG":
        if _has_transparency(img):
            img = _flatten_white_background(img)
        elif img.mode != "RGB":
            img = img.convert("RGB")

    if pillow_format == "WEBP" and img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if img.mode in ("LA", "PA") else "RGB")

    buf = io.BytesIO()
    opts = dict(SAVE_OPTIONS.get(pillow_format, {}))
    if quality and pillow_format in ("JPEG", "WEBP"):
        opts["quality"] = quality
    img.save(buf, format=pillow_format, **opts)
    buf.seek(0)
    return buf.getvalue()


@app.route("/convert", methods=["POST"])
def convert():
    if "image" not in request.files:
        return jsonify({"error": "No image file provided. Use 'image' field."}), 400

    file = request.files["image"]
    target_fmt = request.form.get("format", "")
    quality = request.form.get("quality", 95)

    if not target_fmt:
        return jsonify({"error": "Target format required. Use 'format' field."}), 400

    try:
        target_fmt = _validate_format(target_fmt)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        quality = int(quality)
        if not 1 <= quality <= 100:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Quality must be an integer between 1 and 100."}), 400

    try:
        input_bytes = file.read()
        if not input_bytes:
            return jsonify({"error": "Empty image file."}), 400
        output_bytes = convert_image(input_bytes, target_fmt, quality)
    except Exception as e:
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 400

    pillow_format = FORMAT_MAP[target_fmt]
    mime = MIME_MAP[pillow_format]
    ext = "jpg" if target_fmt in ("jpg", "jpeg") else target_fmt
    filename = os.path.splitext(file.filename or "image")[0] + f".{ext}"

    return send_file(
        io.BytesIO(output_bytes),
        mimetype=mime,
        as_attachment=True,
        download_name=filename,
    )


@app.route("/convert/file", methods=["POST"])
def convert_file():
    path = request.json.get("path", "") if request.is_json else ""
    target_fmt = request.json.get("format", "") if request.is_json else ""
    quality = request.json.get("quality", 95) if request.is_json else 95
    output_path = request.json.get("output", "") if request.is_json else ""

    if not path or not target_fmt:
        return jsonify({"error": "'path' and 'format' are required."}), 400

    try:
        target_fmt = _validate_format(target_fmt)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if not os.path.isfile(path):
        return jsonify({"error": f"File not found: {path}"}), 404

    try:
        quality = int(quality)
    except (ValueError, TypeError):
        return jsonify({"error": "Quality must be an integer between 1 and 100."}), 400

    try:
        with open(path, "rb") as f:
            input_bytes = f.read()
        output_bytes = convert_image(input_bytes, target_fmt, quality)
    except Exception as e:
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 400

    if not output_path:
        ext = "jpg" if target_fmt in ("jpg", "jpeg") else target_fmt
        output_path = os.path.splitext(path)[0] + f".{ext}"

    with open(output_path, "wb") as f:
        f.write(output_bytes)

    return jsonify(
        {
            "message": "Conversion successful.",
            "output": os.path.abspath(output_path),
            "size_bytes": len(output_bytes),
        }
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "supported_formats": sorted(SUPPORTED_FORMATS)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
