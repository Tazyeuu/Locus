import socket
import threading
import cv2
import numpy as np
import pickle
import struct
import time
import sounddevice as sd
import sys
import uuid
from collections import deque

DEFAULT_SERVER_HOST = '127.0.0.1'
AUDIO_PORT = 9999
VIDEO_PORT = 9998
CHAT_PORT = 9997

VIDEO_WIDTH = 480
VIDEO_HEIGHT = 360
FPS_LIMIT = 30
JPEG_QUALITY = 70
AUDIO_RATE = 22050
AUDIO_CHANNELS = 1
AUDIO_CHUNK = 1024
AUDIO_DTYPE = 'int16'
JITTER_BUFFER_SIZE = 5

class AVClient:
    def __init__(self):
        self.running = True
        self.video_frames = {}
        self.frames_lock = threading.Lock()
        self.client_id = str(uuid.uuid4())
        self.jitter_buffer = deque(maxlen=JITTER_BUFFER_SIZE)

        self.server_host = input(f"Masukkan IP Server (default: {DEFAULT_SERVER_HOST}): ") or DEFAULT_SERVER_HOST
        self.username = input("Masukkan username Anda: ")
        if not self.username:
            self.username = f"Guest-{np.random.randint(100, 999)}"

        print(f"Menghubungkan ke {self.server_host} sebagai {self.username}...")

        self.audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.video_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.chat_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.audio_socket.settimeout(5)
        self.video_socket.settimeout(5)
        self.chat_socket.settimeout(5)

        try:
            self.cap = cv2.VideoCapture(0)
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, VIDEO_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, VIDEO_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, FPS_LIMIT)

            self.audio_output_stream = sd.OutputStream(
                samplerate=AUDIO_RATE,
                channels=AUDIO_CHANNELS,
                dtype=AUDIO_DTYPE
            )
        except Exception as e:
            print(f"Error inisialisasi hardware (kamera/mic/speaker): {e}")
            self.running = False

    def send_data(self, sock, data):
        if not self.running:
            return
        try:
            message = len(data).to_bytes(4, 'big') + data
            sock.sendall(message)
        except (socket.timeout, BrokenPipeError, ConnectionResetError) as e:
            print(f"Peringatan: Gagal mengirim data. {e}")
        except Exception as e:
            print(f"Error fatal mengirim data: {e}")
            self.stop()


    def audio_callback(self, indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)

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

                full_data = b''
                while len(full_data) < msg_len:
                    packet = self.audio_socket.recv(msg_len - len(full_data))
                    if not packet: break
                    full_data += packet

                sender_id = full_data[:36].decode('utf-8')
                audio_data_raw = full_data[36:]

                if sender_id != self.client_id:
                    audio_data = np.frombuffer(audio_data_raw, dtype=AUDIO_DTYPE)
                    self.jitter_buffer.append(audio_data)

            except (socket.timeout, ConnectionResetError):
                continue
            except Exception as e:
                if self.running:
                    print(f"Error menerima audio: {e}")
                break

    def start_audio_stream(self):
        """Memulai thread penerima audio dan stream input/output audio."""
        threading.Thread(target=self.receive_audio, daemon=True).start()
        threading.Thread(target=self.audio_playback_thread, daemon=True).start()
        try:
            self.audio_output_stream.start()
            # sd.InputStream berjalan di thread-nya sendiri
            with sd.InputStream(samplerate=AUDIO_RATE, channels=AUDIO_CHANNELS,
                                blocksize=AUDIO_CHUNK, dtype='float32',
                                callback=self.audio_callback):
                while self.running:
                    time.sleep(0.1)
        except Exception as e:
            if self.running:
                print(f"Error pada stream audio: {e}")
            self.stop()

    # --- FUNGSI VIDEO ---

    def receive_video(self):
        """Thread untuk menerima dan memproses frame video dari server."""
        while self.running:
            try:
                # 1. Terima header
                header = self.video_socket.recv(4)
                if not header: break
                msg_len = int.from_bytes(header, 'big')

                # 2. Terima payload (dibungkus server)
                full_data = b''
                while len(full_data) < msg_len:
                    packet = self.video_socket.recv(msg_len - len(full_data))
                    if not packet: break
                    full_data += packet

                sender_id = full_data[:36].decode('utf-8')

                if sender_id != self.client_id:
                    video_payload_raw = full_data[36:]
                    video_payload = pickle.loads(video_payload_raw)
                    sender_username = video_payload['username']
                    encoded_frame_data = video_payload['frame']
                    frame = cv2.imdecode(np.frombuffer(encoded_frame_data, np.uint8), cv2.IMREAD_COLOR)

                    if frame is not None:
                        with self.frames_lock:
                            self.video_frames[sender_username] = frame
                    else:
                        print(f"Peringatan: Menerima frame video yang rusak dari {sender_username}")

            except (socket.timeout, ConnectionResetError):
                continue
            except Exception as e:
                if self.running:
                    print(f"CRITICAL Error menerima/memproses video: {e}")

    def send_video(self):
        """Thread untuk mengambil frame dari webcam dan mengirimkannya."""
        target_delay = 1 / FPS_LIMIT
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

        while self.running and self.cap.isOpened():
            loop_start_time = time.time()
            ret, frame = self.cap.read()
            if not ret:
                print("Error: Gagal membaca frame dari webcam.")
                time.sleep(0.5)
                continue

            # Resize frame agar konsisten
            frame = cv2.resize(frame, (VIDEO_WIDTH, VIDEO_HEIGHT))

            # Simpan frame lokal untuk ditampilkan
            with self.frames_lock:
                # Gunakan username sebagai key, bukan 'local'
                self.video_frames[self.username] = frame

            # Encode dan pickle
            result, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
            if result:
                # Bungkus frame dengan username
                data_to_send = pickle.dumps({
                    'username': self.username,
                    'frame': encoded_frame.tobytes()
                })
                self.send_data(self.video_socket, data_to_send)

            # Atur FPS secara manual
            elapsed = time.time() - loop_start_time
            sleep_duration = target_delay - elapsed
            if sleep_duration > 0:
                time.sleep(sleep_duration)

    def display_videos(self):
        """Loop utama untuk merender semua frame video dalam satu grid."""
        while self.running:
            with self.frames_lock:
                frames_to_display = self.video_frames.copy()

            frames = list(frames_to_display.items())

            if not frames:
                # Tampilan default jika tidak ada frame
                grid = np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8)
                cv2.putText(grid, "Menunggu...", (50, VIDEO_HEIGHT // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            else:
                # --- Logika Grid ---
                num_frames = len(frames)

                # Tulis username di setiap frame
                processed_frames = []
                for username, frame in frames:
                    # Pastikan frame tidak kosong
                    if frame is None or frame.size == 0:
                        frame = np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8)
                        cv2.putText(frame, "No Signal", (50, VIDEO_HEIGHT // 2),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

                    # Tambahkan overlay nama
                    cv2.rectangle(frame, (0, 0), (len(username) * 10 + 20, 30), (0, 0, 0), -1)
                    cv2.putText(frame, username, (10, 22), cv2.FONT_HERSHEY_SIMPLEX,
                                0.6, (255, 255, 255), 1)
                    processed_frames.append(frame)

                # Susun grid
                if num_frames == 1:
                    grid = processed_frames[0]
                elif num_frames == 2:
                    grid = np.hstack(processed_frames)
                elif num_frames <= 4:
                    # 2x2 grid
                    while len(processed_frames) < 4:
                        processed_frames.append(np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8))
                    row1 = np.hstack(processed_frames[0:2])
                    row2 = np.hstack(processed_frames[2:4])
                    grid = np.vstack([row1, row2])
                else:
                    # 3x3 grid (maks 9)
                    while len(processed_frames) < 9:
                        processed_frames.append(np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8))
                    row1 = np.hstack(processed_frames[0:3])
                    row2 = np.hstack(processed_frames[3:6])
                    row3 = np.hstack(processed_frames[6:9])
                    grid = np.vstack([row1, row2, row3])
                # --- Akhir Logika Grid ---

            cv2.imshow('SyncSpace Conference Room (Tekan \'q\' untuk keluar)', grid)

            if cv2.waitKey(1) == ord('q'):
                self.stop()

    # --- FUNGSI CHAT (BARU) ---

    def send_chat(self, text_message):
        """Mengirim pesan chat ke server."""
        try:
            payload = {
                'username': self.username,
                'text': text_message
            }
            self.send_data(self.chat_socket, pickle.dumps(payload))
        except Exception as e:
            print(f"Error mengirim chat: {e}")

    def receive_chat(self):
        """Thread untuk menerima dan menampilkan pesan chat."""
        while self.running:
            try:
                # 1. Terima header
                header = self.chat_socket.recv(4)
                if not header: break
                msg_len = int.from_bytes(header, 'big')

                # 2. Terima payload (dibungkus server)
                full_data = b''
                while len(full_data) < msg_len:
                    packet = self.chat_socket.recv(msg_len - len(full_data))
                    if not packet: break
                    full_data += packet

                sender_id = full_data[:36].decode('utf-8')

                if sender_id != self.client_id:
                    chat_payload_raw = full_data[36:]
                    chat_payload = pickle.loads(chat_payload_raw)
                    print(f"[{chat_payload['username']}]: {chat_payload['text']}")

            except (socket.timeout, ConnectionResetError):
                continue
            except Exception as e:
                if self.running:
                    print(f"Error menerima chat: {e}")
                break

    def chat_input_loop(self):
        """Thread untuk menangani input chat dari pengguna di konsol."""
        print("\n--- Mulai Sesi Chat --- (Ketik pesan dan tekan Enter)")
        while self.running:
            try:
                message = input() # Ini akan mem-blok thread ini, tapi tidak apa-apa
                if message and self.running:
                    self.send_chat(message)
            except EOFError:
                self.stop() # Terjadi jika input ditutup
            except Exception as e:
                if self.running:
                    print(f"Error pada input chat: {e}")
                self.stop()

    # --- FUNGSI UTAMA (START/STOP) ---

    def start(self):
        """Menghubungkan ke server dan memulai semua thread."""
        if not self.running:
            print("Gagal memulai, hardware tidak ditemukan.")
            return

        try:
            print("Menghubungkan ke server audio...")
            self.audio_socket.connect((self.server_host, AUDIO_PORT))
            print("Menghubungkan ke server video...")
            self.video_socket.connect((self.server_host, VIDEO_PORT))
            print("Menghubungkan ke server chat...")
            self.chat_socket.connect((self.server_host, CHAT_PORT))
        except Exception as e:
            print(f"❌ Gagal terhubung ke {self.server_host}: {e}")
            self.stop()
            return

        print(f"✅ Berhasil terhubung ke {self.server_host}!")

        # Memulai semua thread
        threading.Thread(target=self.start_audio_stream, daemon=True).start()
        threading.Thread(target=self.receive_video, daemon=True).start()
        threading.Thread(target=self.send_video, daemon=True).start()
        threading.Thread(target=self.receive_chat, daemon=True).start()
        threading.Thread(target=self.chat_input_loop, daemon=True).start()

        # Loop display video berjalan di main thread
        self.display_videos()

        # Setelah display_videos selesai (karena 'q' ditekan)
        self.stop()

    def stop(self):
        """Membersihkan semua koneksi dan stream."""
        if not self.running:
            return # Hindari stop ganda

        self.running = False
        print("🛑 Menghentikan aplikasi...")

        if hasattr(self, 'audio_output_stream'):
            self.audio_output_stream.stop()
            self.audio_output_stream.close()

        # Beri waktu agar thread lain menyadari self.running == False
        time.sleep(0.5)

        # Tutup semua socket
        self.audio_socket.close()
        self.video_socket.close()
        self.chat_socket.close()

        # Rilis hardware
        if hasattr(self, 'cap'):
            self.cap.release()
        cv2.destroyAllWindows()
        print("Selesai.")


if __name__ == "__main__":
    client = AVClient()
    client.start()