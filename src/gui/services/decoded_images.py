from PyQt6.QtGui import QImage

from src.services.icon_worker import IconResponse


def decoded_image(response: IconResponse) -> QImage:
    return QImage(response.pixels, response.width, response.height, QImage.Format.Format_RGBA8888).copy()
