"""
TCP bridge for serial port.
Forwards data from a Windows COM port to a TCP client (Docker container).
Run on Windows: python serial_bridge.py
"""
import serial
import socket
import sys
import threading

PORT = "COM6"
BAUD = 9600
TCP_PORT = 3241


def main():
    print(f"Opening serial port {PORT} at {BAUD} baud...")
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open {PORT}: {e}")
        sys.exit(1)

    # Probe uses \r line endings only, so read until \r
    ser.readline = lambda: ser.read_until(b'\r')

    print(f"Listening on TCP port {TCP_PORT}...")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(1)

    while True:
        print("Waiting for Docker container to connect...")
        conn, addr = srv.accept()
        print(f"Connected from {addr}")

        stop_event = threading.Event()

        def serial_to_tcp():
            while not stop_event.is_set():
                try:
                    data = ser.readline()
                    if data:
                        # Append \n so container readline() works
                        data = data + b'\n'
                        print(f"  -> {data.strip()}")
                        conn.sendall(data)
                except serial.SerialException as e:
                    print(f"Serial read error: {e}")
                    stop_event.set()
                    break
                except (OSError, BrokenPipeError) as e:
                    print(f"TCP send error: {e}")
                    stop_event.set()
                    break

        def tcp_to_serial():
            while not stop_event.is_set():
                try:
                    data = conn.recv(1024)
                    if not data:
                        stop_event.set()
                        break
                    ser.write(data)
                except (OSError, ConnectionResetError):
                    stop_event.set()
                    break

        t1 = threading.Thread(target=serial_to_tcp, daemon=True)
        t2 = threading.Thread(target=tcp_to_serial, daemon=True)
        t1.start()
        t2.start()

        t1.join()
        stop_event.set()

        try:
            conn.close()
        except Exception:
            pass

        print("Client disconnected. Waiting for new connection...")


if __name__ == "__main__":
    main()
