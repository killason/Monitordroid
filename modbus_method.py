# ============================================================
# MODBUS RTU METHODS
#
# Здесь находится ВСЯ логика Modbus RTU.
#
# Этот файл НЕ зависит от:
#   - Kivy
#   - Android
#   - usbserial4a
#   - pyserial
#
# На вход parser получает произвольные куски байтов.
# На выходе feed() возвращает готовые Modbus RTU кадры.
# ============================================================


# ============================================================
# CRC16 MODBUS
# ============================================================

def modbus_crc(data):
    """
    Расчёт CRC16 Modbus.

    Возвращает integer 0..65535.
    """

    crc = 0xFFFF

    for byte in data:

        crc ^= byte

        for _ in range(8):

            if crc & 1:

                crc >>= 1
                crc ^= 0xA001

            else:

                crc >>= 1

    return crc


def crc_ok(frame):
    """
    Проверяет CRC готового Modbus RTU кадра.
    """

    if len(frame) < 4:
        return False

    calculated = modbus_crc(
        frame[:-2]
    )

    received = (
        frame[-2]
        | (frame[-1] << 8)
    )

    return calculated == received


# ============================================================
# FRAME LENGTH CANDIDATES
# ============================================================

def candidate_lengths(buffer):
    """
    Возвращает возможные длины Modbus RTU кадра
    для находящегося в начале buffer function code.

    Важно:

    USB _read() не определяет границы Modbus.
    Поэтому здесь рассматриваются допустимые
    структуры конкретной Modbus-функции.

    CRC затем определяет, какой вариант настоящий.
    """

    if len(buffer) < 2:
        return []

    function = buffer[1]


    # --------------------------------------------------------
    # Exception response
    #
    # address
    # function | 0x80
    # exception code
    # CRC
    #
    # = 5 bytes
    # --------------------------------------------------------

    if function & 0x80:

        return [5]


    # --------------------------------------------------------
    # 01 Read Coils
    # 02 Read Discrete Inputs
    # 03 Read Holding Registers
    # 04 Read Input Registers
    #
    # REQUEST:
    #
    # address
    # function
    # start address 2
    # quantity      2
    # CRC            2
    #
    # = 8 bytes
    #
    # RESPONSE:
    #
    # address
    # function
    # byte count
    # data
    # CRC
    # --------------------------------------------------------

    if function in (1, 2, 3, 4):

        result = [8]

        if len(buffer) >= 3:

            byte_count = buffer[2]

            response_length = (
                3
                + byte_count
                + 2
            )

            result.append(
                response_length
            )

        return result


    # --------------------------------------------------------
    # 05 Write Single Coil
    # 06 Write Single Register
    #
    # Request  = 8
    # Response = 8
    # --------------------------------------------------------

    if function in (5, 6):

        return [8]


    # --------------------------------------------------------
    # 07 Read Exception Status
    #
    # Response = 4
    # --------------------------------------------------------

    if function == 7:

        return [4]


    # --------------------------------------------------------
    # 0B Get Comm Event Counter
    #
    # Response = 8
    # --------------------------------------------------------

    if function == 11:

        return [8]


    # --------------------------------------------------------
    # 0C Get Comm Event Log
    #
    # Variable response.
    #
    # Не пытаемся угадывать здесь.
    # --------------------------------------------------------

    if function == 12:

        return []


    # --------------------------------------------------------
    # 0F Write Multiple Coils
    #
    # RESPONSE:
    #   8 bytes
    #
    # REQUEST:
    #
    # address
    # function
    # start address 2
    # quantity      2
    # byte count    1
    # data          N
    # CRC           2
    #
    # = 9 + N
    # --------------------------------------------------------

    if function == 15:

        result = [8]

        if len(buffer) >= 7:

            byte_count = buffer[6]

            request_length = (
                9
                + byte_count
            )

            result.append(
                request_length
            )

        return result


    # --------------------------------------------------------
    # 10 / 16 Write Multiple Registers
    #
    # RESPONSE:
    #   8 bytes
    #
    # REQUEST:
    #   9 + byte_count
    # --------------------------------------------------------

    if function == 16:

        result = [8]

        if len(buffer) >= 7:

            byte_count = buffer[6]

            request_length = (
                9
                + byte_count
            )

            result.append(
                request_length
            )

        return result


    # --------------------------------------------------------
    # 11 / 0x0B already above
    # --------------------------------------------------------


    # --------------------------------------------------------
    # 22 / 0x16 Mask Write Register
    #
    # Request  = 10
    # Response = 10
    # --------------------------------------------------------

    if function == 22:

        return [10]


    # --------------------------------------------------------
    # 23 / 0x17 Read/Write Multiple Registers
    #
    # REQUEST:
    #
    # address       1
    # function      1
    # read address  2
    # read qty      2
    # write address 2
    # write qty     2
    # byte count    1
    # data          N
    # CRC           2
    #
    # = 13 + N
    #
    # RESPONSE:
    #
    # address
    # function
    # byte count
    # data
    # CRC
    #
    # = 5 + N
    # --------------------------------------------------------

    if function == 23:

        result = []

        # Possible response
        if len(buffer) >= 3:

            byte_count = buffer[2]

            response_length = (
                5
                + byte_count
            )

            result.append(
                response_length
            )

        # Possible request
        if len(buffer) >= 11:

            byte_count = buffer[10]

            request_length = (
                13
                + byte_count
            )

            result.append(
                request_length
            )

        return result


    # --------------------------------------------------------
    # 43 / 0x2B
    #
    # Encapsulated Interface Transport.
    #
    # Пока специально не угадываем длину.
    # --------------------------------------------------------

    if function == 43:

        return []


    # --------------------------------------------------------
    # Unknown function
    # --------------------------------------------------------

    return []


# ============================================================
# STREAM PARSER
# ============================================================

class ModbusRTUParser:
    """
    Потоковый parser Modbus RTU.

    ВАЖНО:

    feed() может получить:

        b'\\x0B\\x03\\x00'

    потом:

        b'\\x01\\x00\\x0F\\x54\\xA4'

    или сразу:

        frame1 + frame2 + frame3

    Для parser это одинаковый поток.

    Возвращает список полностью собранных
    и проверенных CRC кадров.
    """

    def __init__(self):

        self.buffer = bytearray()


    def feed(self, data):
        """
        Добавляет новые байты в поток.

        Возвращает список готовых кадров.
        """

        if not data:
            return []

        self.buffer.extend(data)

        frames = []

        while True:

            frame = self._extract_one()

            if frame is None:
                break

            frames.append(frame)

        return frames


    def _extract_one(self):
        """
        Пытается извлечь один кадр из начала buffer.

        Если полного кадра пока нет:
            None

        Если кадр найден:
            bytes(frame)
        """

        while True:

            # Минимальный Modbus RTU кадр:
            #
            # address
            # function
            # ...
            # CRC
            #
            # минимум 4 байта

            if len(self.buffer) < 4:

                return None


            # ------------------------------------------------
            # Slave address
            # ------------------------------------------------

            address = self.buffer[0]

            if not (
                1 <= address <= 247
            ):

                # Это не допустимый slave address.
                # Сдвигаем поток на один байт.

                del self.buffer[0]

                continue


            # ------------------------------------------------
            # Получаем возможные длины
            # ------------------------------------------------

            candidates = candidate_lengths(
                self.buffer
            )


            # Неизвестная функция.

            if not candidates:

                del self.buffer[0]

                continue


            incomplete = False


            # ------------------------------------------------
            # Проверяем все допустимые длины
            # ------------------------------------------------

            for length in candidates:

                if length < 4:
                    continue


                # Кадр ещё не полностью пришёл.

                if len(self.buffer) < length:

                    incomplete = True

                    continue


                candidate = bytes(
                    self.buffer[:length]
                )


                # ------------------------------------------------
                # CRC
                # ------------------------------------------------

                if crc_ok(candidate):

                    # Удаляем только найденный кадр.

                    del self.buffer[
                        :length
                    ]

                    return candidate


            # ------------------------------------------------
            # Один из вариантов ещё может быть
            # неполным.
            # ------------------------------------------------

            if incomplete:

                return None


            # ------------------------------------------------
            # Ни один кандидат не дал правильного CRC.
            #
            # Синхронизируемся со следующим байтом.
            # ------------------------------------------------

            del self.buffer[0]


    def clear(self):
        """
        Полностью очистить внутренний buffer.
        """

        self.buffer.clear()


    def buffered_size(self):
        """
        Сколько байт сейчас находится в buffer.
        """

        return len(self.buffer)


# ============================================================
# FRAME HELPERS
# ============================================================

def frame_address(frame):
    """
    Slave address.
    """

    if not frame:
        return None

    return frame[0]


def frame_function(frame):
    """
    Function code без флага exception.
    """

    if len(frame) < 2:
        return None

    return frame[1] & 0x7F


def is_exception(frame):
    """
    True если это Modbus exception response.
    """

    if len(frame) < 2:
        return False

    return bool(
        frame[1] & 0x80
    )


def frame_payload(frame):
    """
    Кадр без CRC.
    """

    if len(frame) < 2:
        return frame

    return frame[:-2]


def frame_crc(frame):
    """
    Возвращает CRC как два байта.
    """

    if len(frame) < 2:
        return b""

    return frame[-2:]


# ============================================================
# DISPLAY FORMAT
# ============================================================

def format_frame(frame):
    """
    Форматирует готовый Modbus кадр
    для отображения в мониторе.

    Пример:

    11 3 0 1 0 15 CRC=54 A4 OK
    """

    if len(frame) < 2:
        return ""


    payload = frame_payload(frame)

    crc = frame_crc(frame)


    payload_text = " ".join(
        str(byte)
        for byte in payload
    )


    crc_text = " ".join(
        f"{byte:02X}"
        for byte in crc
    )


    if crc_ok(frame):

        status = "OK"

    else:

        status = "FAULT"


    return (
        f"{payload_text} "
        f"CRC={crc_text} "
        f"{status}"
    )