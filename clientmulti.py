import socket
import threading
import cv2
import numpy as np
import pickle
import time
import sounddevice as sd
import sys
import uuid
from collections import deque
import customtkinter as ctk
from PIL import Image, ImageTk

# --- Constants ---
DEFAULT_SERVER_HOST = '127.0.0.1'
AUDIO_PORT = 9999
VIDEO_PORT = 9998
CHAT_PORT = 9997

VIDEO_WIDTH = 320
VIDEO_HEIGHT = 240
FPS_LIMIT = 20
JPEG_QUALITY = 80
AUDIO_RATE = 22050
AUDIO_CHANNELS = 1
AUDIO_CHUNK = 1024
AUDIO_DTYPE = 'int16'
JITTER_BUFFER_SIZE = 5

# --- UI Theme ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SyncSpace Conference")
        self.geometry("1200x720")
        self.video_labels = {}
        self.video_frames = {}
        self.frames_lock = threading.Lock()
        self.client = None

        # --- Main Layout ---
        self.grid_columnconfigure(0, weight=4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- Video Grid ---
        self.video_frame = ctk.CTkFrame(self, fg_color="black")
        self.video_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # --- Controls & Chat (Right Panel) ---
        self.right_panel = ctk.CTkFrame(self)
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.right_panel.grid_rowconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(1, weight=0)
        self.right_panel.grid_rowconfigure(2, weight=0)


        self.setup_chat()
        self.setup_controls()
        self.login_screen()

    def login_screen(self):
        server_ip = ctk.CTkInputDialog(text="Enter Server IP:", title="Login").get_input()
        username = ctk.CTkInputDialog(text="Enter Username:", title="Login").get_input()

        if not server_ip:
            server_ip = DEFAULT_SERVER_HOST
        if not username:
            username = f"Guest-{np.random.randint(100, 999)}"

        self.client = AVClient(server_ip, username, self)
        self.client.start()
        self.after(100, self.update_video_grid)

    def setup_controls(self):
        control_frame = ctk.CTkFrame(self.right_panel)
        control_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        control_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.mute_button = ctk.CTkButton(control_frame, text="Mute", command=self.toggle_mute)
        self.mute_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.camera_button = ctk.CTkButton(control_frame, text="Cam Off", command=self.toggle_camera)
        self.camera_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.leave_button = ctk.CTkButton(control_frame, text="Leave", command=self.leave_call, fg_color="red")
        self.leave_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")

    def setup_chat(self):
        chat_frame = ctk.CTkFrame(self.right_panel)
        chat_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_box = ctk.CTkTextbox(chat_frame, state="disabled")
        self.chat_box.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        self.chat_input = ctk.CTkEntry(chat_frame, placeholder_text="Type a message...")
        self.chat_input.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.chat_input.bind("<Return>", self.send_chat_message)

        self.send_button = ctk.CTkButton(chat_frame, text="Send", command=self.send_chat_message)
        self.send_button.grid(row=1, column=1, padx=5, pady=5)

    def send_chat_message(self, event=None):
        message = self.chat_input.get()
        if message and self.client:
            self.client.send_chat(message)
            self.chat_input.delete(0, "end")

    def toggle_mute(self):
        if self.client:
            self.client.toggle_mute()

    def toggle_camera(self):
        if self.client:
            self.client.toggle_camera()

    def leave_call(self):
        if self.client:
            self.client.stop()
        self.destroy()

    def update_video_grid(self):
        with self.frames_lock:
            for username, frame in self.video_frames.items():
                if username not in self.video_labels:
                    self.video_labels[username] = ctk.CTkLabel(self.video_frame, text="")
                    self.video_labels[username].pack(expand=True, fill="both", padx=5, pady=5)

                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                img_tk = ImageTk.PhotoImage(image=img)

                self.video_labels[username].configure(image=img_tk)
                self.video_labels[username].image = img_tk

        self.after(int(1000/FPS_LIMIT), self.update_video_grid)


class AVClient:
    def __init__(self, server_host, username, app):
        self.app = app
        self.server_host = server_host
        self.username = username
        self.running = False
        self.muted = False
        self.camera_on = True

        self.client_id = str(uuid.uuid4())
        self.jitter_buffer = deque(maxlen=JITTER_BUFFER_SIZE)

        self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def start(self):
        self.running = True
        try:
            self.cap = cv2.VideoCapture(0)
            self.audio_output_stream = sd.OutputStream(samplerate=AUDIO_RATE, channels=AUDIO_CHANNELS, dtype=AUDIO_DTYPE)
            self.audio_input_stream = sd.InputStream(samplerate=AUDIO_RATE, channels=AUDIO_CHANNELS, dtype='float32', callback=self.audio_callback)

            self.audio_socket.connect((self.server_host, AUDIO_PORT))
            self.send_data(self.audio_socket, self.client_id.encode('utf-8'))

            self.video_socket.connect((self.server_host, VIDEO_PORT))
            self.send_data(self.video_socket, self.client_id.encode('utf-8'))

            self.chat_socket.connect((self.server_host, CHAT_PORT))
            self.send_data(self.chat_socket, self.client_id.encode('utf-8'))

            threading.Thread(target=self.receive_audio, daemon=True).start()
            threading.Thread(target=self.receive_video, daemon=True).start()
            threading.Thread(target=self.receive_chat, daemon=True).start()
            threading.Thread(target=self.send_video, daemon=True).start()
            threading.Thread(target=self.audio_playback_thread, daemon=True).start()
            self.audio_output_stream.start()
            self.audio_input_stream.start()

        except Exception as e:
            print(f"Failed to start client: {e}")
            self.running = False

    def stop(self):
        self.running = False
        if hasattr(self, 'audio_input_stream'): self.audio_input_stream.stop()
        if hasattr(self, 'audio_output_stream'): self.audio_output_stream.stop()
        if hasattr(self, 'cap'): self.cap.release()
        self.audio_socket.close()
        self.video_socket.close()
        self.chat_socket.close()

    def send_data(self, sock, data):
        if not self.running: return
        try:
            message = len(data).to_bytes(4, 'big') + data
            sock.sendall(message)
        except (socket.error, BrokenPipeError):
            print("Connection to server lost.")
            self.stop()

    def audio_callback(self, indata, frames, time, status):
        if status: print(status)
        if not self.muted:
            compressed_data = (indata * 32767).astype(AUDIO_DTYPE).tobytes()
            self.send_data(self.audio_socket, compressed_data)

    def audio_playback_thread(self):
        while self.running:
            if len(self.jitter_buffer) > 0:
                audio_data = self.jitter_buffer.popleft()
                self.audio_output_stream.write(audio_data)
            else:
                time.sleep(0.01)

    def receive_audio(self):
        while self.running:
            try:
                header = self.audio_socket.recv(4)
                if not header: break
                msg_len = int.from_bytes(header, 'big')
                data = self._receive_all(self.audio_socket, msg_len)
                sender_id = data[:36].decode('utf-8')
                if sender_id != self.client_id:
                    audio_data = np.frombuffer(data[36:], dtype=AUDIO_DTYPE)
                    self.jitter_buffer.append(audio_data)
            except Exception as e:
                print(f"Error receiving audio: {e}")
                break

    def _receive_all(self, sock, n):
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet: return None
            data += packet
        return data

    def send_video(self):
        while self.running:
            if not self.camera_on:
                time.sleep(0.1)
                continue
            ret, frame = self.cap.read()
            if not ret: continue

            frame_resized = cv2.resize(frame, (VIDEO_WIDTH, VIDEO_HEIGHT))
            with self.app.frames_lock:
                self.app.video_frames[self.username] = frame_resized

            _, buffer = cv2.imencode('.jpg', frame_resized, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            data_to_send = pickle.dumps({'username': self.username, 'frame': buffer.tobytes()})
            self.send_data(self.video_socket, data_to_send)
            time.sleep(1/FPS_LIMIT)

    def receive_video(self):
        while self.running:
            try:
                header = self.video_socket.recv(4)
                if not header: break
                msg_len = int.from_bytes(header, 'big')
                data = self._receive_all(self.video_socket, msg_len)

                sender_id = data[:36].decode('utf-8')
                if sender_id != self.client_id:
                    payload = pickle.loads(data[36:])
                    username = payload['username']
                    frame_data = payload['frame']
                    frame = cv2.imdecode(np.frombuffer(frame_data, np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        with self.app.frames_lock:
                            self.app.video_frames[username] = frame
            except Exception as e:
                print(f"Error receiving video: {e}")
                break

    def send_chat(self, message):
        payload = {'username': self.username, 'text': message}
        self.send_data(self.chat_socket, pickle.dumps(payload))

    def receive_chat(self):
        while self.running:
            try:
                header = self.chat_socket.recv(4)
                if not header: break
                msg_len = int.from_bytes(header, 'big')
                data = self._receive_all(self.chat_socket, msg_len)

                sender_id = data[:36].decode('utf-8')
                if sender_id != self.client_id:
                    payload = pickle.loads(data[36:])
                    self.app.chat_box.configure(state="normal")
                    self.app.chat_box.insert("end", f"[{payload['username']}]: {payload['text']}\n")
                    self.app.chat_box.configure(state="disabled")
            except Exception as e:
                print(f"Error receiving chat: {e}")
                break

    def toggle_mute(self):
        self.muted = not self.muted
        self.app.mute_button.configure(text="Unmute" if self.muted else "Mute")

    def toggle_camera(self):
        self.camera_on = not self.camera_on
        self.app.camera_button.configure(text="Cam On" if not self.camera_on else "Cam Off")

if __name__ == "__main__":
    app = App()
    app.mainloop()
