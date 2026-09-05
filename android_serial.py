def find_rs485():
    from usb4a import usb

    VID = 0x067B
    PID = 0x2303

    for device in usb.get_usb_device_list():
        if (
            device.getVendorId() == VID
            and device.getProductId() == PID
        ):
            return device

    return None


def has_permission(device):
    from usb4a import usb
    return usb.has_usb_permission(device)


def request_permission(device):
    from usb4a import usb
    usb.request_usb_permission(device)


def open_rs485(
    device,
    baudrate=9600,
    bytesize=8,
    parity='N',
    stopbits=1
):
    from usbserial4a import serial4a

    port = serial4a.get_serial_port(
        device.getDeviceName(),
        baudrate,
        bytesize,
        parity,
        stopbits
    )

    if port is None or not port.is_open:
        raise RuntimeError("Не удалось открыть PL2303")

    return port