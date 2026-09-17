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
    stopbits=1,
    timeout=0.1,
):
    from usbserial4a import serial4a

    port = serial4a.get_serial_port(
        device.getDeviceName(),
        baudrate,
        bytesize,
        parity,
        stopbits
    )

    if port is None or not getattr(port, "is_open", False):
        raise RuntimeError("Не удалось открыть PL2303")

    # Android usbserial4a is picky: timeout is configured after open, never passed
    # into get_serial_port(). Keep it short enough to avoid the whole UI hanging.
    if timeout is not None:
        timeout_seconds = float(timeout)
        timeout_ms = max(10, int(timeout_seconds * 1000))

        for attr in ("timeout", "read_timeout", "readTimeout"):
            try:
                setattr(port, attr, timeout_seconds)
            except Exception:
                pass

            try:
                setattr(port, attr, timeout_ms)
            except Exception:
                pass

        for method_name in ("setTimeout", "set_read_timeout", "setReadTimeout"):
            method = getattr(port, method_name, None)
            if callable(method):
                try:
                    method(timeout_seconds)
                except TypeError:
                    try:
                        method(timeout_ms)
                    except Exception:
                        pass
                except Exception:
                    pass

    return port