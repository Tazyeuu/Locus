import sys
import socket
import threading
import cv2
import numpy as np
import pickle
import time
import sounddevice as sd
import struct
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout, 
                             QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
                             QFrame, QSizePolicy, QInputDialog, QMessageBox, 
                             QScrollArea, QLineEdit, QTextEdit, QGraphicsOpacityEffect, QDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot, QSize, QTimer, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QPen, QIcon, QBrush
import os


os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"

DEFAULT_IP = '127.0.0.1'
UDP_PORT, TCP_PORT = 9999, 9997
VIDEO_W, VIDEO_H = 1280, 720 
FPS = 30
JPEG_QUAL = 95
MAX_PACKET_SIZE = 60000 

STYLESHEET = """
QMainWindow, QDialog { background-color: #121212; }
QLabel { color: white; font-family: "Segoe UI"; }
QLineEdit {
    padding: 12px; border-radius: 8px; background: #252525; color: white; border: 1px solid #444; font-size: 14px;
}
QLineEdit:focus { border: 1px solid #2cc985; }
QPushButton {
    border-radius: 20px; font-family: "Segoe UI"; font-size: 14px; font-weight: bold; color: white; border: none;
}
QPushButton:hover { margin-top: -2px; }
QTextEdit {
    background-color: transparent; border: none; color: #eee; font-family: "Segoe UI"; font-size: 13px; padding: 10px;
}
"""

# HELPERS
def create_locus_icon(size=64, font_size=40):
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0,0,0,0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#2cc985")))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size-4, size-4)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", font_size, QFont.Weight.Bold))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "L")
    painter.end()
    return QIcon(pixmap)

def create_button_icon(emoji, size=32, crossed_out=False):
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0,0,0,0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont("Segoe UI Emoji", size-6)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    if crossed_out:
        pen = QPen(QColor("#ff4444"))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        padding = 4
        painter.drawLine(padding, padding, size-padding, size-padding)
    painter.end()
    return QIcon(pixmap)

# dialog
class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Login - Locus")
        self.setWindowIcon(create_locus_icon())
        self.setFixedSize(400, 500)
        self.setStyleSheet(STYLESHEET)
        self.username = ""
        self.ip = ""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(40, 40, 40, 40)
        
        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_locus_icon(100, 60).pixmap(100, 100))
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_lbl)
        
        title = QLabel("Locus")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 32px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title)
        
        self.input_user = QLineEdit()
        self.input_user.setPlaceholderText("Username")
        layout.addWidget(self.input_user)
        
        self.input_ip = QLineEdit()
        self.input_ip.setPlaceholderText("Server IP")
        layout.addWidget(self.input_ip)
        
        btn_connect = QPushButton("Join Meeting")
        btn_connect.setFixedHeight(50)
        btn_connect.setStyleSheet("background-color: #2cc985; font-size: 16px; border-radius: 25px;")
        btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_connect.clicked.connect(self.check_login)
        layout.addWidget(btn_connect)
        layout.addStretch()

    def check_login(self):
        u = self.input_user.text().strip()
        i = self.input_ip.text().strip()
        if not u: return
        if not i: return
        self.username = u
        self.ip = i
        self.accept()

class ToastOverlay(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            background-color: rgba(0, 0, 0, 200); color: white; font-weight: bold; font-size: 16px; 
            border-radius: 15px; padding: 10px 20px;
        """)
        self.hide()
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(1500)
        self.anim.finished.connect(self.hide)

    def show_message(self, text, icon="ℹ️"):
        self.setText(f"{icon}  {text}")
        self.adjustSize()
        p_geo = self.parent().geometry()
        x = (p_geo.width() - self.width()) // 2
        y = p_geo.height() - 150
        self.move(x, y)
        self.show(); self.raise_()
        self.anim.stop()
        self.anim.setKeyValueAt(0, 0.0); self.anim.setKeyValueAt(0.1, 1.0)
        self.anim.setKeyValueAt(0.8, 1.0); self.anim.setKeyValueAt(1.0, 0.0)
        self.anim.start()

# card
class VideoCard(QWidget):
    def __init__(self, username):
        super().__init__()
        self.username = username
        self.frame = None
        self.is_off = True; self.is_mute = False; self.is_deaf = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 180)
        self.font_name = QFont("Segoe UI", 11, QFont.Weight.Bold)
        self.font_icon = QFont("Segoe UI Emoji", 20)
        self.font_big = QFont("Segoe UI", 18, QFont.Weight.Bold)

    def update_data(self, qimage, mute, deaf, off):
        self.frame = qimage; self.is_mute = mute; self.is_deaf = deaf; self.is_off = off
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        path = QPen(QColor("#333"), 2)
        painter.setPen(path); painter.setBrush(QColor("#000"))
        painter.drawRoundedRect(rect.adjusted(2,2,-2,-2), 15, 15)
        draw_rect = rect.adjusted(4,4,-4,-4)
        
        if not self.is_off and self.frame:
            img_w, img_h = self.frame.width(), self.frame.height()
            draw_w, draw_h = draw_rect.width(), draw_rect.height()
            scale = min(draw_w/img_w, draw_h/img_h)
            new_w, new_h = int(img_w*scale), int(img_h*scale)
            x = draw_rect.x() + (draw_w - new_w) // 2
            y = draw_rect.y() + (draw_h - new_h) // 2
            scaled = self.frame.scaled(new_w, new_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(x, y, QPixmap.fromImage(scaled))
        else:
            painter.setPen(QColor("#555")); painter.setFont(self.font_big)
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignCenter, "CAMERA OFF")

        name_metrics = painter.fontMetrics()
        name_w = name_metrics.horizontalAdvance(self.username) + 20
        pill_rect = draw_rect.adjusted(10, draw_rect.height()-40, 0, 0)
        pill_rect.setWidth(name_w); pill_rect.setHeight(30)
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(0, 0, 0, 150))
        painter.drawRoundedRect(pill_rect, 15, 15)
        painter.setPen(QColor("white")); painter.setFont(self.font_name)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, self.username)

        icon_size = 30; margin = 10
        current_x = draw_rect.right() - margin - icon_size
        current_y = draw_rect.top() + margin
        painter.setFont(self.font_icon)
        
        def draw_icon(emoji, color_line="#ff4444"):
            painter.setPen(QColor("white"))
            icon_rect = QRect(current_x, current_y, icon_size, icon_size)
            painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, emoji)
            pen = QPen(QColor(color_line)); pen.setWidth(3); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(current_x + 5, current_y + 5, current_x + icon_size - 5, current_y + icon_size - 5)

        if self.is_deaf: draw_icon("🎧"); current_x -= (icon_size + 5)
        if self.is_mute: draw_icon("🎙️")

# BACKEND
class BackendWorker(QThread):
    sig_video = pyqtSignal(str, object, bool, bool, bool)
    sig_chat = pyqtSignal(str, str)
    sig_connected = pyqtSignal()
    sig_disconnected = pyqtSignal()
    
    def __init__(self, username, ip):
        super().__init__()
        self.username = username
        self.ip = ip
        self.running = True
        self.is_mute = False; self.is_deaf = False; self.is_cam = True
        
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 200)
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.stream_out = sd.OutputStream(channels=1, samplerate=22050)
        self.stream_out.start()
        self.frame_buffer = {} 
        self.frame_seq = 0

        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not self.cap.isOpened(): self.cap = cv2.VideoCapture(1, cv2.CAP_DSHOW)
        if self.cap.isOpened():
            self.cap.set(3, VIDEO_W); self.cap.set(4, VIDEO_H); self.cap.set(5, FPS)
            try: self.cap.set(cv2.CAP_PROP_SHARPNESS, 0)
            except: pass

    def run(self):
        try:
            self.tcp.connect((self.ip, TCP_PORT))
            self.sig_connected.emit()
            self.send_udp_control({'type': 'hello', 'u': self.username})
            
            t_cam = threading.Thread(target=self.loop_camera, daemon=True)
            t_udp = threading.Thread(target=self.loop_udp, daemon=True)
            t_tcp = threading.Thread(target=self.loop_tcp, daemon=True)
            t_cam.start(); t_udp.start(); t_tcp.start()
            
            while self.running: time.sleep(1)
        except: 
            self.sig_disconnected.emit()

    def loop_tcp(self):
        while self.running:
            try:
                head = self.tcp.recv(4)
                if not head: 
                    self.running = False
                    self.sig_disconnected.emit()
                    break
                
                l = int.from_bytes(head, 'big')
                d = b''
                while len(d) < l: d += self.tcp.recv(l-len(d))
                obj = pickle.loads(d)
                self.sig_chat.emit(obj['u'], obj['t'])
            except: 
                self.running = False
                self.sig_disconnected.emit()
                break

    # cam
    def loop_camera(self):
        while self.running:
            start = time.time()
            frame_ready = False
            if self.is_cam and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    frame_ready = True
                    frame = cv2.bilateralFilter(frame, 5, 75, 75)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
                    self.sig_video.emit(self.username, qimg, self.is_mute, self.is_deaf, False)
                    _, b = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUAL])
                    self.send_video_fragments(b.tobytes())
            
            if not frame_ready:
                self.sig_video.emit(self.username, None, self.is_mute, self.is_deaf, True)
                self.send_udp_control({'type': 'offcam', 'u': self.username, 'mute': self.is_mute, 'deaf': self.is_deaf})
            time.sleep(max(0, (1.0/FPS) - (time.time()-start)))

    def send_video_fragments(self, data):
        self.frame_seq = (self.frame_seq + 1) % 256
        chunks = [data[i:i+MAX_PACKET_SIZE] for i in range(0, len(data), MAX_PACKET_SIZE)]
        total = len(chunks)
        user_b = self.username.encode('utf-8')
        flags = (self.is_mute << 1) | self.is_deaf
        for i, chunk in enumerate(chunks):
            header = struct.pack("BBBBB", 0xFF, self.frame_seq, i, total, len(user_b))
            packet = header + user_b + struct.pack("B", flags) + chunk
            try: self.udp.sendto(packet, (self.ip, UDP_PORT))
            except: pass

    def send_udp_control(self, data):
        try: self.udp.sendto(pickle.dumps(data, 5), (self.ip, UDP_PORT))
        except: pass

    def loop_udp(self):
        while self.running:
            try:
                data, _ = self.udp.recvfrom(65536)
                if data[0] == 0xFF: self.process_fragment(data)
                else: 
                    obj = pickle.loads(data)
                    self.process_control(obj)
            except: pass

    def process_fragment(self, data):
        try:
            seq, idx, total, u_len = struct.unpack("BBBB", data[1:5])
            username = data[5:5+u_len].decode('utf-8')
            flags = data[5+u_len]
            chunk = data[6+u_len:]
            is_mute = bool(flags & 2); is_deaf = bool(flags & 1)

            if username not in self.frame_buffer: self.frame_buffer[username] = {}
            user_buf = self.frame_buffer[username]
            
            if seq not in user_buf:
                user_buf.clear()
                user_buf[seq] = {'chunks': {}, 'total': total, 'ts': time.time()}
            
            frame_data = user_buf[seq]
            frame_data['chunks'][idx] = chunk
            
            if len(frame_data['chunks']) == total:
                sorted_chunks = sorted(frame_data['chunks'].items())
                full_data = b''.join([c[1] for c in sorted_chunks])
                frame_arr = np.frombuffer(full_data, np.uint8)
                f = cv2.imdecode(frame_arr, cv2.IMREAD_COLOR)
                if f is not None:
                    rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                    qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
                    self.sig_video.emit(username, qimg, is_mute, is_deaf, False)
                del user_buf[seq]
        except: pass

    def process_control(self, obj):
        ptype = obj.get('type')
        if ptype == 'audio' and not self.is_deaf:
            raw = np.frombuffer(obj['d'], dtype=np.int16)
            self.stream_out.write(raw.astype(np.float32)/32767)
        elif ptype == 'offcam':
            self.sig_video.emit(obj['u'], None, obj['mute'], obj['deaf'], True)

    def audio_callback(self, indata, frames, time, status):
        if self.running and not self.is_mute and not self.is_deaf:
            packed = (indata * 32767).astype(np.int16).tobytes()
            self.send_udp_control({'type': 'audio', 'u': self.username, 'd': packed})

    def stop(self):
        self.running = False
        try: self.cap.release()
        except: pass
        try: self.udp.close()
        except: pass
        try: self.tcp.close()
        except: pass

# MAIN
class MainWindow(QMainWindow):
    def __init__(self, username, ip):
        super().__init__()
        self.setWindowTitle("Locus")
        self.resize(1280, 720)
        self.setStyleSheet(STYLESHEET)
        self.setWindowIcon(create_locus_icon())
        
        self.backend = BackendWorker(username, ip)
        self.backend.sig_video.connect(self.update_grid)
        self.backend.sig_chat.connect(self.update_chat)
        self.backend.sig_disconnected.connect(self.on_server_down)
        
        self.cards = {} 
        self.setup_ui()
        self.toast = ToastOverlay(self)
        
        self.stream_in = sd.InputStream(callback=self.backend.audio_callback, channels=1, samplerate=22050)
        self.stream_in.start()
        self.backend.start()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.setSpacing(0)

        # HEADER
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(60)
        h_layout = QHBoxLayout(header)
        logo_lbl = QLabel()
        logo_lbl.setPixmap(create_locus_icon(32, 20).pixmap(32, 32))
        title = QLabel("Locus")
        title.setObjectName("HeaderTitle")
        h_layout.addWidget(logo_lbl)
        h_layout.addWidget(title)
        h_layout.addStretch()
        main_layout.addWidget(header)

        # CONTENT
        content = QHBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(10)
        self.grid_layout.setContentsMargins(10,10,10,10)
        scroll.setWidget(self.grid_container)
        content.addWidget(scroll, stretch=1)

        # Sidebar
        self.sidebar = QFrame()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(0)
        s_layout = QVBoxLayout(self.sidebar)
        
        lbl_chat = QLabel("Meeting Chat")
        lbl_chat.setStyleSheet("color:white; font-weight:bold; margin-bottom:5px;")
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setPlaceholderText("No messages yet...")
        
        input_layout = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type a message...")
        self.chat_input.returnPressed.connect(self.action_send_chat)
        btn_send = QPushButton("➤")
        btn_send.setFixedSize(40, 40)
        btn_send.setStyleSheet("background-color: #3a7ebf; border-radius: 20px;")
        btn_send.clicked.connect(self.action_send_chat)
        
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(btn_send)
        s_layout.addWidget(lbl_chat)
        s_layout.addWidget(self.chat_area)
        s_layout.addLayout(input_layout)
        content.addWidget(self.sidebar)
        main_layout.addLayout(content)

        # BOTTOM BAR
        bottom = QFrame()
        bottom.setObjectName("BottomBar")
        bottom.setFixedHeight(80)
        b_layout = QHBoxLayout(bottom)
        b_layout.setSpacing(15)
        b_layout.addStretch()

        self.btn_mute = self.create_btn("Mute", "#2cc985", "🎙️")
        self.btn_deaf = self.create_btn("Deafen", "#2cc985", "🎧")
        self.btn_cam = self.create_btn("Camera", "#2cc985", "📷")
        self.btn_chat = self.create_btn("Chat", "#555", "💬")
        self.btn_leave = self.create_btn("Leave", "#ff4444", "🚪")

        self.btn_mute.clicked.connect(self.action_mute)
        self.btn_deaf.clicked.connect(self.action_deaf)
        self.btn_cam.clicked.connect(self.action_cam)
        self.btn_chat.clicked.connect(self.action_toggle_chat)
        self.btn_leave.clicked.connect(self.close)

        b_layout.addWidget(self.btn_mute)
        b_layout.addWidget(self.btn_deaf)
        b_layout.addWidget(self.btn_cam)
        b_layout.addWidget(self.btn_chat) 
        b_layout.addWidget(self.btn_leave)
        b_layout.addStretch()
        main_layout.addWidget(bottom)

        self.anim_sidebar = QPropertyAnimation(self.sidebar, b"maximumWidth")
        self.anim_sidebar.setDuration(300)
        self.anim_sidebar.setEasingCurve(QEasingCurve.Type.OutCubic)

    def create_btn(self, text, color, emoji):
        btn = QPushButton(text)
        btn.setFixedSize(130, 45)
        btn.setIcon(create_button_icon(emoji, crossed_out=False))
        btn.setIconSize(QSize(24, 24))
        btn.setStyleSheet(f"background-color: {color}; text-align: left; padding-left: 15px;")
        return btn

    def on_server_down(self):
        self.backend.stop()
        QMessageBox.critical(self, "Disconnected", "Server has been stopped by host.")
        sys.exit()

    def action_toggle_chat(self):
        is_open = self.sidebar.width() > 0
        start = 320 if is_open else 0
        end = 0 if is_open else 320
        self.anim_sidebar.setStartValue(start)
        self.anim_sidebar.setEndValue(end)
        self.anim_sidebar.start()
        c = "#555" if is_open else "#3a7ebf"
        self.btn_chat.setStyleSheet(f"background-color: {c}; text-align: left; padding-left: 15px;")

    def action_send_chat(self):
        text = self.chat_input.text()
        if text:
            try:
                d = pickle.dumps({'u': self.backend.username, 't': text})
                h = len(d).to_bytes(4, 'big')
                self.backend.tcp.sendall(h + d)
                self.chat_input.clear()
                self.update_chat("Me", text)
            except: pass

    def action_mute(self):
        if self.backend.is_deaf:
            self.toast.show_message("Undeafen first!", "⚠️")
            return
        self.backend.is_mute = not self.backend.is_mute
        self.update_audio_ui()
        self.toast.show_message("Muted" if self.backend.is_mute else "Unmuted", "🔇" if self.backend.is_mute else "🎙️")

    def action_deaf(self):
        self.backend.is_deaf = not self.backend.is_deaf
        if self.backend.is_deaf:
            self.backend.is_mute = True
            msg = "Deafened"
            icon = "🔕"
        else:
            self.backend.is_mute = False 
            msg = "Undeafened"
            icon = "🎧"
        self.update_audio_ui()
        self.toast.show_message(msg, icon)

    def update_audio_ui(self):
        mute_c = "#e0a82e" if self.backend.is_mute else "#2cc985"
        self.btn_mute.setStyleSheet(f"background-color: {mute_c}; text-align: left; padding-left: 15px;")
        self.btn_mute.setText("Unmute" if self.backend.is_mute else "Mute")
        self.btn_mute.setIcon(create_button_icon("🎙️", crossed_out=self.backend.is_mute))

        deaf_c = "#e63946" if self.backend.is_deaf else "#2cc985"
        self.btn_deaf.setStyleSheet(f"background-color: {deaf_c}; text-align: left; padding-left: 15px;")
        self.btn_deaf.setText("Undeaf" if self.backend.is_deaf else "Deafen")
        self.btn_deaf.setIcon(create_button_icon("🎧", crossed_out=self.backend.is_deaf))

    def action_cam(self):
        self.backend.is_cam = not self.backend.is_cam
        c = "#2cc985" if self.backend.is_cam else "#555"
        self.btn_cam.setStyleSheet(f"background-color: {c}; text-align: left; padding-left: 15px;")
        self.btn_cam.setText("Camera" if self.backend.is_cam else "Off")
        self.btn_cam.setIcon(create_button_icon("📷", crossed_out=not self.backend.is_cam))
        self.toast.show_message("Camera ON" if self.backend.is_cam else "Camera OFF")

    def update_grid(self, username, qimg, mute, deaf, off):
        if username not in self.cards:
            card = VideoCard(username)
            self.cards[username] = card
            count = len(self.cards)
            cols = int(count**0.5) + 1 if count > 1 else 1
            for i, (u, w) in enumerate(self.cards.items()):
                self.grid_layout.addWidget(w, i // cols, i % cols)
        self.cards[username].update_data(qimg, mute, deaf, off)

    def update_chat(self, user, msg):
        c = "#3a7ebf" if user == "Me" else "#2cc985"
        self.chat_area.append(f"<b style='color:{c}'>{user}:</b> {msg}")

    def closeEvent(self, event):
        self.backend.stop()
        self.stream_in.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec() == QDialog.DialogCode.Accepted:
        w = MainWindow(login.username, login.ip)
        w.show()
        sys.exit(app.exec())
    else:
        sys.exit()