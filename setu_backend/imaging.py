import io

from django.core.files.base import ContentFile
from PIL import Image


def compress_uploaded_image(image_field_file, max_dimension=1600, quality=82):
    """
    Downscale + re-encode an image at upload time, in place on the given
    FieldFile, before Django writes it to storage.

    Previously post images and avatars were stored exactly as uploaded —
    a phone photo straight out of the camera (often 10-20MB, 4000px+ wide)
    would then be served at that same full size to *every* viewer of that
    post/profile, even though the UI only ever displays it at a few
    hundred px (post-image / avatar / avatar-img in index.css). That's a
    lot of wasted bandwidth and slow feed-image loads for something the
    upload flow can fix once, at write time, instead of every read.

    Safe to call unconditionally: no-ops on falsy input and swallows
    decode errors so a corrupt/unsupported file still gets stored (same
    behaviour as before this existed) rather than blocking the save.
    """
    if not image_field_file:
        return
    try:
        img = Image.open(image_field_file)
        img.load()
    except Exception:
        return

    try:
        # Keep PNG as PNG (logos/screenshots with transparency), otherwise
        # normalize to JPEG — smaller for photos, which is the vast
        # majority of avatar/post-image uploads.
        out_format = "PNG" if img.format == "PNG" else "JPEG"
        if out_format == "JPEG" and img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        if img.width > max_dimension or img.height > max_dimension:
            img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buffer = io.BytesIO()
        if out_format == "JPEG":
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
        else:
            img.save(buffer, format="PNG", optimize=True)
        buffer.seek(0)

        name = image_field_file.name or "upload"
        if out_format == "JPEG" and not name.lower().endswith((".jpg", ".jpeg")):
            name = name.rsplit(".", 1)[0] + ".jpg"

        # save(..., save=False): only swap the in-memory file content:
        # the model's own .save() call (right after this runs) is what
        # actually persists it, so this shouldn't trigger a second write.
        image_field_file.save(name, ContentFile(buffer.read()), save=False)
    except Exception:
        pass
