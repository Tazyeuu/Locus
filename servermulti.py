import socket
import threading
import uuid
from queue import Queue
import time

# --- Constants ---
HOST = '0.0.0.0'
AUDIO_PORT = 9999
VIDEO_PORT = 9998
CHAT_PORT = 9997
MAX_QUEUE_SIZE = 10  # To prevent memory bloat

# --- Global State ---
clients = {}
lock = threading.Lock()

def broadcast_message(sender_id, data, data_type):
    """
    Puts a message into the outgoing queue for every client except the sender.
    This function is non-blocking.
    """
    with lock:
        for client_id, client in clients.items():
            if client_id != sender_id:
                if client[data_type]['queue'].full():
                    print(f"Warning: Queue full for {client_id} on {data_type}. Dropping packet.")
                    continue
                client[data_type]['queue'].put(data)

def sender_thread(client_id, data_type):
    """
    A dedicated thread for each client's data stream (audio, video, chat)
    that sends messages from their personal queue.
    """
    while True:
        try:
            client_socket = clients[client_id][data_type]['socket']
            queue = clients[client_id][data_type]['queue']

            message = queue.get() # This is a blocking call
            if message is None: # Sentinel value to terminate the thread
                break

            client_socket.sendall(message)
        except (socket.error, BrokenPipeError):
            print(f"Sender thread for {client_id} ({data_type}) detected a broken pipe. Terminating.")
            break
        except KeyError:
            # Client has been removed
            break
        except Exception as e:
            print(f"Error in sender thread for {client_id} ({data_type}): {e}")
            break

def handle_connection(client_socket, client_addr, data_type):
    client_id = None
    try:
        header = client_socket.recv(4)
        if not header: return
        id_len = int.from_bytes(header, 'big')
        client_id = client_socket.recv(id_len).decode('utf-8')

        with lock:
            if client_id not in clients:
                clients[client_id] = {'addr': client_addr}

            # Each stream (audio, video, chat) gets its own socket, queue, and sender thread
            clients[client_id][data_type] = {
                'socket': client_socket,
                'queue': Queue(maxsize=MAX_QUEUE_SIZE)
            }
            threading.Thread(target=sender_thread, args=(client_id, data_type), daemon=True).start()
            print(f"Connection for {data_type} from {client_addr} associated with client ID {client_id}")

        while True:
            header = client_socket.recv(4)
            if not header: break
            msg_len = int.from_bytes(header, 'big')

            data = b''
            while len(data) < msg_len:
                packet = client_socket.recv(msg_len - len(data))
                if not packet: raise ConnectionResetError("Connection lost during payload.")
                data += packet

            message_to_broadcast = (client_id.encode('utf-8') + data)
            full_message = len(message_to_broadcast).to_bytes(4, 'big') + message_to_broadcast

            broadcast_message(client_id, full_message, data_type)

    except (ConnectionResetError, ConnectionAbortedError):
        print(f"Connection from {client_addr} forcibly closed.")
    except Exception as e:
        print(f"Error on connection from {client_addr}: {e}")
    finally:
        print(f"Cleaning up connection for {client_id} from {client_addr}")
        with lock:
            if client_id and client_id in clients:
                # Signal sender thread to terminate
                if data_type in clients[client_id]:
                    clients[client_id][data_type]['queue'].put(None)
                    clients[client_id][data_type]['socket'].close()
                    del clients[client_id][data_type]

                # Check if any other connections (audio, video, chat) are left
                if not any(dt in clients[client_id] for dt in ['audio', 'video', 'chat']):
                    print(f"All connections for client {client_id} are closed. Removing client.")
                    del clients[client_id]


def start_listener(port, data_type):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, port))
    server.listen(5)
    print(f"✅ Server {data_type} is running on {HOST}:{port}")
    while True:
        try:
            client_socket, addr = server.accept()
            threading.Thread(target=handle_connection, args=(client_socket, addr, data_type), daemon=True).start()
        except Exception as e:
            print(f"Error accepting connections: {e}")

if __name__ == "__main__":
    for port, dtype in [(AUDIO_PORT, "audio"), (VIDEO_PORT, "video"), (CHAT_PORT, "chat")]:
        threading.Thread(target=start_listener, args=(port, dtype), daemon=True).start()

    print("🚀 Server is running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Server is shutting down.")
