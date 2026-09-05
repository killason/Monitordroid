from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
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

        root = BoxLayout(
            orientation="vertical"
        )

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

        self.scroll.add_widget(self.log)
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

    # ========================================================
    # LOG
    # ========================================================

    def log_line(self, text):
        print(text)

        label = Label(
            text=text,
            size_hint_y=None,
            height="22dp",
            halign="left",
            valign="middle",
            text_size=(None, None),
            font_size="15sp",
            color=(1, 1, 1, 1),
        )
        label.bind(
            size=lambda instance, value:
                setattr(instance, "text_size", (instance.width, None))
        )

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
                self.open_port()
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

                self.log_line(
                    "USB permission получен"
                )

                self.open_port()

        except BaseException as e:
            Clock.unschedule(
                self.check_permission
            )

            self.show_error(e)

    def open_port(self):
        try:
            self.ser = open_rs485(
                self.device,
                baudrate=BAUDRATE,
                bytesize=8,
                parity="N",
                stopbits=1,
            )

            self.log_line("RS485 OPEN")
            self.log_line("9600 8N1")
            self.log_line("Готов. Нажмите СТАРТ.")

        except BaseException as e:
            self.show_error(e)

    # ========================================================
    # START / STOP
    # ========================================================

    def start_monitoring(self, *args):
        if self.ser is None:
            self.log_line(
                "ERROR: RS485 порт не открыт"
            )
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

        chooser = FileChooserListView(
            path=str(Path.home()),
            filters=["*.txt"],
        )

        filename_input = TextInput(
            text="modbus_log.txt",
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
