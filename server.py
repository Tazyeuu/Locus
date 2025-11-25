import socket
import threading
import time
import sys

HOST = '0.0.0.0'
UDP_PORT = 9999
TCP_CHAT_PORT = 9997

udp_clients = {} 
tcp_clients = []
lock = threading.Lock()
server_running = True

def udp_listener():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024 * 10)
    except: pass
    
    try:
        udp_sock.bind((HOST, UDP_PORT))
        print(f"✅ UDP Server (Video) running on {HOST}:{UDP_PORT}")
    except OSError as e:
        print(f"❌ Gagal bind UDP: {e}")
        return

    while server_running:
        try:
            udp_sock.settimeout(1.0) 
            try:
                data, addr = udp_sock.recvfrom(65536)
            except socket.timeout:
                continue 

            with lock:
                # Register Client
                if addr not in udp_clients:
                    print(f"🎥 New UDP Client: {addr}")
                udp_clients[addr] = time.time()
                
                # Cleanup
                cutoff = time.time() - 5
                inactive = [k for k, v in udp_clients.items() if v < cutoff]
                for k in inactive: del udp_clients[k]
                
                targets = list(udp_clients.keys())

            # Broadcast
            for target in targets:
                if target != addr:
                    try: udp_sock.sendto(data, target)
                    except: pass
        except Exception as e: 
            print(f"UDP Loop Error: {e}")
    
    udp_sock.close()

def handle_tcp(client, addr):
    print(f"🔗 TCP Chat Connected: {addr}")
    with lock:
        tcp_clients.append(client)
    try:
        while server_running:
            header = client.recv(4)
            if not header: break
            length = int.from_bytes(header, 'big')
            data = b''
            while len(data) < length:
                chunk = client.recv(length - len(data))
                if not chunk: break
                data += chunk
            
            if len(data) == length:
                msg = header + data
                with lock:
                    for c in tcp_clients:
                        if c != client:
                            try: c.sendall(msg)
                            except: pass
            else: break
    except: pass
    finally:
        print(f"❌ TCP Disconnected: {addr}")
        with lock:
            if client in tcp_clients: tcp_clients.remove(client)
        client.close()

def tcp_listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, TCP_CHAT_PORT))
    server.listen(5)
    server.settimeout(1.0)
    print(f"✅ TCP Server (Chat) running on {HOST}:{TCP_CHAT_PORT}")
    
    while server_running:
        try:
            client, addr = server.accept()
            threading.Thread(target=handle_tcp, args=(client, addr), daemon=True).start()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"TCP Accept Error: {e}")
    server.close()

if __name__ == "__main__":
    t_udp = threading.Thread(target=udp_listener, daemon=True)
    t_tcp = threading.Thread(target=tcp_listener, daemon=True)
    
    t_udp.start()
    t_tcp.start()
    
    print("🚀 SERVER BERJALAN. Tekan Ctrl+C untuk mematikan.")
    
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 MEMATIKAN SERVER...")
        server_running = False
        
        with lock:
            for client in tcp_clients:
                try: client.close()
                except: pass
        print("👋 Server Off.")