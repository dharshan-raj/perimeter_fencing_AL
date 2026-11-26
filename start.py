import socket
import uvicorn

HOST = "0.0.0.0"
PORT = 8000

if __name__ == "__main__":
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        already_running = probe.connect_ex(("127.0.0.1", PORT)) == 0

    if already_running:
        print(f"Backend is already running at http://localhost:{PORT}; reusing the existing server.")
    else:
        uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
