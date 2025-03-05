import io
import logging
import os
import requests

from PIL import Image


log = logging.getLogger(__name__)


def _convert_image_to_jpg_in_memory(image_bytes):
    # Open the WebP image from bytes
    image = Image.open(io.BytesIO(image_bytes))

    # Create a BytesIO object to hold the JPG image data
    jpg_buffer = io.BytesIO()

    # Convert the WebP image to JPG and save it in the BytesIO buffer
    image.convert("RGB").save(jpg_buffer, format="JPEG")

    # Get the JPG image data as bytes
    jpg_bytes = jpg_buffer.getvalue()

    return jpg_bytes


def download_and_convert_to_jpg(url):
    current_file_name_based_on_url = os.path.basename(url)

    # Some urls from youtube have a query string attached
    tmp = current_file_name_based_on_url.split('?')
    filename = tmp[0]
    try:
        bare_filename, ext = filename.rsplit('.', 1)
    except ValueError:
        ext = 'jpg'

    contents = requests.get(url).content
    final_ext = ext

    if final_ext and final_ext.lower() == 'webp':
        try:
            conversion_tmp = _convert_image_to_jpg_in_memory(contents)
            contents = conversion_tmp
            final_ext = 'jpg'
        except (ValueError, TypeError, OSError):
            log.exception(f'Failure to convert {ext} to jpg')
            final_ext = ext

    return contents, final_ext
