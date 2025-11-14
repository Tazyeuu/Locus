import socket
import threading
import pickle

HOST = '0.0.0.0'
AUDIO_PORT = 9999
VIDEO_PORT = 9998
CHAT_PORT = 9997  

clients = {} 
lock = threading.Lock()

def broadcast(sender_addr, data, data_type):
    with lock:
        for addr, connections in list(clients.items()):
            if addr != sender_addr and data_type in connections:
                try:
                    connections[data_type].sendall(data)
                except (socket.error, BrokenPipeError):
                    print(f"Koneksi {data_type} ke {addr} terputus, membersihkan...")
                    connections[data_type].close()
                    if data_type in connections:
                         del connections[data_type]
                    if not connections:
                        if addr in clients:
                            del clients[addr]

def handle_connection(client_socket, client_addr, data_type):
    print(f"Koneksi {data_type} diterima dari {client_addr}")
    client_ip = client_addr[0]
    
    with lock:
        clients.setdefault(client_ip, {})[data_type] = client_socket

    try:
        while True:
            header = client_socket.recv(4)
            if not header:
                print(f"Koneksi {data_type} dari {client_ip} ditutup (header kosong).")
                break
            msg_len = int.from_bytes(header, 'big')

            data = b''
            while len(data) < msg_len:
                packet = client_socket.recv(msg_len - len(data))
                if not packet:
                    raise ConnectionResetError("Koneksi terputus saat menerima data payload.")
                data += packet

            message_to_broadcast = pickle.dumps({'id': client_ip, 'data': data})
            
            broadcast_header = len(message_to_broadcast).to_bytes(4, 'big')
            
            broadcast(client_ip, broadcast_header + message_to_broadcast, data_type)

    except (ConnectionResetError, ConnectionAbortedError):
        print(f"Koneksi {data_type} dari {client_ip} ditutup paksa.")
    except Exception as e:
        print(f"Error pada koneksi {data_type} dari {client_ip}: {e}")
    finally:
        with lock:
            if client_ip in clients and data_type in clients[client_ip]:
                clients[client_ip][data_type].close()
                del clients[client_ip][data_type]
                if not clients[client_ip]: 
                    del clients[client_ip]
        print(f"Koneksi {data_type} dari {client_ip} ditutup. Sisa klien: {len(clients)}")

def start_listener(port, data_type):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, port))
    server.listen(5)
    print(f"✅ Server {data_type} berjalan di {HOST}:{port}")

    while True:
        try:
            client_socket, addr = server.accept()
            thread = threading.Thread(target=handle_connection, args=(client_socket, addr, data_type))
            thread.daemon = True
            thread.start()
        except Exception as e:
            print(f"Error menerima koneksi: {e}")

if __name__ == "__main__":
    threading.Thread(target=start_listener, args=(AUDIO_PORT, "audio"), daemon=True).start()
    threading.Thread(target=start_listener, args=(VIDEO_PORT, "video"), daemon=True).start()
    threading.Thread(target=start_listener, args=(CHAT_PORT, "chat"), daemon=True).start()
    
    print("🚀 Server berjalan untuk Audio, Video, dan Chat. Tekan Ctrl+C untuk keluar.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\n🛑 Server dimatikan.")