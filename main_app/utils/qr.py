import qrcode
from qrcode.constants import ERROR_CORRECT_M
from qrcode.image.svg import SvgPathImage


def qr_svg(data):
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
        image_factory=SvgPathImage,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image(attrib={'class': 'on-site-user-device-qr__svg'})
    return image.to_string(encoding='unicode')
