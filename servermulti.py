import socket
import threading
import pickle
import uuid

HOST = '0.0.0.0'
AUDIO_PORT = 9999
VIDEO_PORT = 9998
CHAT_PORT = 9997

clients = {}
lock = threading.Lock()

def broadcast(sender_id, data, data_type):
    with lock:
        # Create a copy of the client items to avoid issues with dictionary size changing during iteration
        for client_key, client_data in list(clients.items()):
            # The sender_id is the unique ID of the client, not the IP
            if client_data['id'] != sender_id and data_type in client_data['connections']:
                try:
                    client_data['connections'][data_type].sendall(data)
                except (socket.error, BrokenPipeError):
                    print(f"Connection {data_type} to {client_data['addr']} lost, cleaning up...")
                    client_data['connections'][data_type].close()
                    del client_data['connections'][data_type]
                    if not client_data['connections']:
                        del clients[client_key]

def handle_connection(client_socket, client_addr, data_type):
    client_key = client_addr[0] # Group by IP address for now
    client_id_to_broadcast = None

    with lock:
        if client_key not in clients:
            # New client
            client_id = str(uuid.uuid4())
            clients[client_key] = {'id': client_id, 'connections': {}, 'addr': client_addr}
            print(f"New client from {client_addr} assigned ID {client_id}")

        clients[client_key]['connections'][data_type] = client_socket
        client_id_to_broadcast = clients[client_key]['id']
        print(f"Connection {data_type} received from {client_addr} for client ID {client_id_to_broadcast}")


    try:
        while True:
            header = client_socket.recv(4)
            if not header:
                print(f"Connection {data_type} from {client_addr} closed (empty header).")
                break
            msg_len = int.from_bytes(header, 'big')

            data = b''
            while len(data) < msg_len:
                packet = client_socket.recv(msg_len - len(data))
                if not packet:
                    raise ConnectionResetError("Connection lost while receiving payload.")
                data += packet

            message_to_broadcast = pickle.dumps({'id': client_id_to_broadcast, 'data': data})
            broadcast_header = len(message_to_broadcast).to_bytes(4, 'big')

            broadcast(client_id_to_broadcast, broadcast_header + message_to_broadcast, data_type)

    except (ConnectionResetError, ConnectionAbortedError):
        print(f"Connection {data_type} from {client_addr} forcibly closed.")
    except Exception as e:
        print(f"Error on connection {data_type} from {client_addr}: {e}")
    finally:
        with lock:
            if client_key in clients:
                if data_type in clients[client_key]['connections']:
                    clients[client_key]['connections'][data_type].close()
                    del clients[client_key]['connections'][data_type]

                # If no connections are left for this client, remove the client
                if not clients[client_key]['connections']:
                    print(f"All connections for client {clients[client_key]['id']} closed. Removing client.")
                    del clients[client_key]
        print(f"Connection {data_type} from {client_addr} closed. Remaining clients: {len(clients)}")

def start_listener(port, data_type):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, port))
    server.listen(5)
    print(f"✅ Server {data_type} is running on {HOST}:{port}")

    while True:
        try:
            client_socket, addr = server.accept()
            thread = threading.Thread(target=handle_connection, args=(client_socket, addr, data_type))
            thread.daemon = True
            thread.start()
        except Exception as e:
            print(f"Error accepting connections: {e}")

if __name__ == "__main__":
    threading.Thread(target=start_listener, args=(AUDIO_PORT, "audio"), daemon=True).start()
    threading.Thread(target=start_listener, args=(VIDEO_PORT, "video"), daemon=True).start()
    threading.Thread(target=start_listener, args=(CHAT_PORT, "chat"), daemon=True).start()

    print("🚀 Server is running for Audio, Video, and Chat. Press Ctrl+C to exit.")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("\n🛑 Server is shutting down.")