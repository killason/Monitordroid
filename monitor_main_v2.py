from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from datetime import datetime
from pathlib import Path

from android_serial import (
    find_rs485,
    has_permission,
    request_permission,
    open_rs485,
)

from modbus_method import ModbusRTUParser, format_frame


BAUDRATE = 9600

# Spinner option lists
BAUD_RATES = ["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"]
DATA_BITS = ["5", "6", "7", "8"]
PARITIES = ["N", "E", "O"]
STOP_BITS = ["1", "1.5", "2"]
PROTOCOLS = ["ModbusRTU"]


def timestamp():
    now = datetime.now()
    return now.strftime("%M:%S.") + f"{now.microsecond // 1000:03d}"


class MonitorScrollView(ScrollView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.do_scroll_x = False
        self.do_scroll_y = True
        self.scroll_type = ["content"]
        self.bar_width = 0


class ModbusMonitorApp(App):

    def build(self):
        self.running = False
        self.read_event = None
        self.device = None
        self.ser = None
        self.parser = ModbusRTUParser()
        self.permission_granted = False
        self.start_after_permission = False

        root = BoxLayout(
            orientation="vertical"
        )

        # ====================================================
        # DROPDOWNS (Spinners) - AT TOP
        # ====================================================

        spinners = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="45dp",
            spacing="6dp",
            padding=[8, 5],
        )

        self.baud_spinner = Spinner(
            text=str(BAUDRATE),
            values=BAUD_RATES,
            size_hint=(None, None),
            size=("90dp", "36dp"),
            font_size="14sp",
        )

        self.bits_spinner = Spinner(
            text="8",
            values=DATA_BITS,
            size_hint=(None, None),
            size=("60dp", "36dp"),
            font_size="14sp",
        )

        self.parity_spinner = Spinner(
            text="N",
            values=PARITIES,
            size_hint=(None, None),
            size=("60dp", "36dp"),
            font_size="14sp",
        )

        self.stop_spinner = Spinner(
            text="1",
            values=STOP_BITS,
            size_hint=(None, None),
            size=("60dp", "36dp"),
            font_size="14sp",
        )

        self.protocol_spinner = Spinner(
            text=PROTOCOLS[0],
            values=PROTOCOLS,
            size_hint=(None, None),
            size=("110dp", "36dp"),
            font_size="14sp",
        )

        spinners.add_widget(self.baud_spinner)
        spinners.add_widget(self.bits_spinner)
        spinners.add_widget(self.parity_spinner)
        spinners.add_widget(self.stop_spinner)
        spinners.add_widget(self.protocol_spinner)

        root.add_widget(spinners)

        # ====================================================
        # SCROLLVIEW + LABELS
        # ====================================================

        self.scroll = MonitorScrollView()

        self.log = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=[0, 0],
            spacing=0,
        )
        self.log.bind(
            minimum_height=self.log.setter("height")
        )

        # Пока строк мало, лог занимает весь экран.
        # Поэтому первые строки остаются сверху, а не "плавают"
        # посередине при первом перерасчёте интерфейса.
        self.scroll.bind(
            height=self._sync_log_height,
            width=self._sync_log_width,
        )

        self.scroll.add_widget(self.log)
        Clock.schedule_once(self._sync_log_height, 0)
        root.add_widget(self.scroll)

        # ====================================================
        # КНОПКИ
        # ====================================================

        buttons = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="55dp",
            spacing="8dp",
            padding=[8, 5],
        )

        self.start_button = Button(
            text="СТАРТ",
            font_size="16sp",
        )

        self.stop_button = Button(
            text="СТОП",
            font_size="16sp",
        )

        self.save_button = Button(
            text="СОХРАНИТЬ",
            font_size="16sp",
        )

        self.start_button.bind(
            on_release=self.start_monitoring
        )

        self.stop_button.bind(
            on_release=self.stop_monitoring
        )

        self.save_button.bind(
            on_release=self.save_log
        )

        buttons.add_widget(self.start_button)
        buttons.add_widget(self.stop_button)
        buttons.add_widget(self.save_button)

        root.add_widget(buttons)

        Clock.schedule_once(
            self.init_usb,
            0
        )

        return root

    def _sync_log_height(self, *args):
        self.log.height = max(
            self.log.minimum_height,
            self.scroll.height,
        )

    def _sync_log_width(self, *args):
        self.log.width = self.scroll.width

    # ========================================================
    # LOG
    # ========================================================

    def log_line(self, text):
        print(text)

        label = Label(
            text=text,
            size_hint_y=None,
            height="20dp",
            halign="left",
            valign="middle",
            text_size=(None, None),
            font_size="15sp",
            color=(1, 1, 1, 1),
        )
        label.text_size = (self.log.width - 20, None)
        self.log.add_widget(label)

        if self.running:
            Clock.schedule_once(self.scroll_to_bottom, 0)

    def scroll_to_bottom(self, dt):
        if not self.running:
            return

        self.scroll.scroll_y = 0

    # ========================================================
    # USB
    # ========================================================

    def init_usb(self, dt):
        try:
            self.log_line(
                "Ищу PL2303 067B:2303..."
            )

            self.device = find_rs485()

            if self.device is None:
                self.log_line(
                    "PL2303 НЕ НАЙДЕН"
                )
                return

            self.log_line(
                "PL2303 найден"
            )

            if has_permission(self.device):
                # Don't open port automatically; open on Start so spinner settings apply
                self.permission_granted = True
                self.log_line(
                    "USB permission есть — порт откроется при нажатии СТАРТ"
                )
            else:
                self.log_line(
                    "Запрашиваю USB permission..."
                )

                request_permission(
                    self.device
                )

                Clock.schedule_interval(
                    self.check_permission,
                    0.2
                )

        except BaseException as e:
            self.show_error(e)

    def check_permission(self, dt):
        try:
            if has_permission(self.device):
                Clock.unschedule(
                    self.check_permission
                )

                self.permission_granted = True

                self.log_line(
                    "USB permission получен"
                )

                # If Start was pressed while waiting for permission, open port and start
                if getattr(self, 'start_after_permission', False):
                    self.start_after_permission = False
                    try:
                        self.open_port()
                        # proceed to start monitoring now that port is open
                        self.start_monitoring()
                    except BaseException as e:
                        self.show_error(e)

        except BaseException as e:
            Clock.unschedule(
                self.check_permission
            )

            self.show_error(e)

    def open_port(self):
        try:
            # Read values from spinners if available, otherwise fall back to defaults
            baud = int(self.baud_spinner.text) if hasattr(self, "baud_spinner") else BAUDRATE
            bytesize = int(self.bits_spinner.text) if hasattr(self, "bits_spinner") else 8
            parity = self.parity_spinner.text if hasattr(self, "parity_spinner") else "N"
            stop_text = self.stop_spinner.text if hasattr(self, "stop_spinner") else "1"
            try:
                stopbits = float(stop_text) if "." in stop_text else int(stop_text)
            except Exception:
                stopbits = 1

            self.ser = open_rs485(
                self.device,
                baudrate=baud,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            )

            self.log_line("RS485 OPEN")
            self.log_line(f"{baud} {bytesize}{parity}{stop_text}")
            self.log_line("Готов. Нажмите СТАРТ.")

        except BaseException as e:
            self.show_error(e)

    # ========================================================
    # START / STOP
    # ========================================================

    def start_monitoring(self, *args):
        # If port isn't open yet, attempt to open it now using spinner values.
        if self.ser is None:
            # Ensure device exists
            if self.device is None:
                # try to find device now
                self.device = find_rs485()
                if self.device is None:
                    self.log_line(
                        "ERROR: RS485 устройство не найдено"
                    )
                    return

            # Ensure permission
            if not has_permission(self.device):
                self.log_line("Запрашиваю USB permission для открытия порта...")
                request_permission(self.device)
                # mark that user wants to start after permission
                self.start_after_permission = True
                Clock.schedule_interval(self.check_permission, 0.2)
                return

            # Open port now (uses spinner values)
            try:
                self.open_port()
            except BaseException as e:
                self.show_error(e)
                return

        if self.running:
            return

        self.running = True
        self.parser.clear()

        self.log_line(
            "----- СТАРТ -----"
        )

        self.read_event = Clock.schedule_once(
            self.read_serial,
            0
        )

    def stop_monitoring(self, *args):
        if not self.running:
            return

        self.running = False

        if self.read_event is not None:
            Clock.unschedule(
                self.read_event
            )
            self.read_event = None

        self.parser.clear()

        # Close serial port and clear buffer
        if self.ser is not None:
            try:
                # Flush any remaining data in buffer
                if hasattr(self.ser, 'reset_input_buffer'):
                    self.ser.reset_input_buffer()
                if hasattr(self.ser, 'reset_output_buffer'):
                    self.ser.reset_output_buffer()
                # Close the port
                self.ser.close()
                self.log_line("RS485 закрыт")
            except BaseException as e:
                self.log_line("WARN: ошибка при закрытии порта: " + repr(e))
            finally:
                self.ser = None

        # После этой строки log_line() уже НЕ вызывает
        # автоматическую прокрутку.
        self.log_line(
            "----- СТОП -----"
        )

    # ========================================================
    # SERIAL READ
    # ========================================================

    def read_serial(self, dt):
        self.read_event = None

        if not self.running:
            return

        try:
            data = self.ser._read()

            if data:
                frames = self.parser.feed(data)

                for frame in frames:
                    self.show_frame(frame)

            if self.running:
                self.read_event = Clock.schedule_once(
                    self.read_serial,
                    0
                )

        except BaseException as e:
            self.running = False
            self.read_event = None
            self.show_error(e)

    # ========================================================
    # MODBUS FRAME
    # ========================================================

    def show_frame(self, frame):
        text = format_frame(frame)

        line = (
            f"[{timestamp()}] "
            + text
        )

        self.log_line(line)

    def get_log_text(self):
        return "\n".join(
            child.text for child in self.log.children[::-1]
        ) + ("\n" if self.log.children else "")

    # ========================================================
    # SAVE
    # ========================================================

    def save_log(self, *args):
        text = self.get_log_text()

        if not text.strip():
            self.log_line(
                "Сохранять нечего."
            )
            return

        start_path = "/storage/emulated/0"
        if not Path(start_path).exists():
            start_path = str(Path.home())

        chooser = FileChooserListView(
            path=start_path,
            filters=["*.txt"],
            dirselect=True,
        )

        filename_input = TextInput(
            text=datetime.now().strftime("%Y-%m-%d_%H-%M-%S.txt"),
            size_hint_y=None,
            height="45dp",
            multiline=False,
        )

        save_button = Button(
            text="СОХРАНИТЬ",
            size_hint_y=None,
            height="50dp",
        )

        cancel_button = Button(
            text="ОТМЕНА",
            size_hint_y=None,
            height="50dp",
        )

        buttons = BoxLayout(
            size_hint_y=None,
            height="50dp",
            spacing="5dp",
        )

        buttons.add_widget(save_button)
        buttons.add_widget(cancel_button)

        layout = BoxLayout(
            orientation="vertical",
            spacing="5dp",
            padding="5dp",
        )

        layout.add_widget(chooser)
        layout.add_widget(filename_input)
        layout.add_widget(buttons)

        popup = Popup(
            title="Сохранить лог",
            content=layout,
            size_hint=(0.95, 0.9),
        )

        def do_save(instance):
            directory = chooser.path
            filename = filename_input.text.strip()

            if not filename:
                filename = "modbus_log.txt"

            if not filename.lower().endswith(".txt"):
                filename += ".txt"

            filepath = Path(directory) / filename

            try:
                filepath.write_text(
                    text,
                    encoding="utf-8"
                )

                popup.dismiss()

                self.log_line(
                    f"Лог сохранён: {filepath}"
                )

            except BaseException as e:
                self.show_error(e)

        save_button.bind(
            on_release=do_save
        )

        cancel_button.bind(
            on_release=popup.dismiss
        )

        popup.open()

    # ========================================================
    # ERROR
    # ========================================================

    def show_error(self, error):
        self.log_line(
            "ERROR: " + repr(error)
        )


if __name__ == "__main__":
    ModbusMonitorApp().run()
