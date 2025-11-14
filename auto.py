import socket
import pyaudio
import threading
import sys

SERVER_HOST = '10.133.144.88' 
SERVER_PORT = 9999

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

class AutoVoiceClient:
    def __init__(self):
        self.p = pyaudio.PyAudio()

        self.recording_stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        self.playing_stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
        
        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        self.running = True

    def connect_to_server(self):
        try:
            self.client_socket.connect((SERVER_HOST, SERVER_PORT))
            print("✅ Berhasil terhubung ke server. Audio Anda sekarang aktif.")
        except Exception as e:
            print(f"❌ Gagal terhubung ke server: {e}")
            self.stop() 

    def receive_data(self):
        while self.running:
            try:
                data = self.client_socket.recv(CHUNK)
                if not data:
                    print("Koneksi server terputus.")
                    break
                self.playing_stream.write(data)
            except socket.error:
                break
            except Exception as e:
                print(f"Error saat menerima data: {e}")
                break
        self.stop()

    def send_data(self):
        while self.running:
            try:
                data = self.recording_stream.read(CHUNK)
                self.client_socket.sendall(data)
            except socket.error:
                break
            except Exception as e:
                print(f"Error saat mengirim data: {e}")
                break
        self.stop()

    def start(self):
        """Memulai semua proses klien."""
        self.connect_to_server()
        if not self.running:
            return

        print("🎤 Mikrofon aktif. Tekan Ctrl+C untuk keluar.")

        receive_thread = threading.Thread(target=self.receive_data)
        send_thread = threading.Thread(target=self.send_data)

        receive_thread.daemon = True
        send_thread.daemon = True

        receive_thread.start()
        send_thread.start()
        
        try:
            while self.running:
                pass
        except KeyboardInterrupt:
            print("\n🛑 Keluar dari program...")
            self.stop()

    def stop(self):
        """Menghentikan semua stream, socket, dan program."""
        if not self.running:
            return
            
        self.running = False
        
        print("Menutup stream audio...")
        self.recording_stream.stop_stream()
        self.recording_stream.close()
        self.playing_stream.stop_stream()
        self.playing_stream.close()
        self.p.terminate()

        print("Menutup koneksi...")
        self.client_socket.close()
        
        sys.exit()


if __name__ == "__main__":
    client = AutoVoiceClient()
    client.start()