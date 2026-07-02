"""
Direct Tor P2P chat + video — pure Python, no WebRTC / STUN / ICE / TURN.

Architecture:
    Alice App  <---- Tor hidden service ---->  Bob App
    alice.onion                                bob.onion

One side runs in LISTEN mode (host): binds a local TCP socket that Tor exposes
as their .onion address. The other side runs in CONNECT mode (dialer): opens
an outbound connection through Tor's local SOCKS5 proxy directly to the
listener's .onion address.

Once the TCP handshake completes, it's a normal full-duplex socket. Text,
video, and audio all share that single connection using a simple
length-prefixed framing protocol:

    [1 byte type] [4 byte big-endian length] [payload]

    type = b'T'  -> payload is UTF-8 text
    type = b'V'  -> payload is a JPEG-encoded video frame
    type = b'A'  -> payload is a chunk of raw PCM16 mono audio

NOTE ON VIDEO/AUDIO OVER TOR:
Tor circuits are high latency and often low bandwidth. Real-time video and
audio will generally be laggy/choppy compared to a normal call, especially
over slow or congested circuits. Defaults below (small video frame size,
modest fps, aggressive JPEG compression, low audio sample rate, small audio
chunks) are chosen to keep both streams as light as possible. Tune
--width/--height/--fps/--quality for video, and --sample-rate/--audio-chunk-ms
for audio, if your circuit is faster, or lower them further if it's
struggling. If you enable both --video and --audio at once over a slow
circuit, expect noticeably more lag on both than running either alone.

Requirements:
    pip install PySocks --break-system-packages          (needed for CONNECT mode)
    pip install opencv-python numpy --break-system-packages   (needed for --video)
    pip install sounddevice numpy --break-system-packages     (needed for --audio)

Usage:
    # On the machine that will be reachable via its onion address:
    python chat_app.py listen --port 8765
    python chat_app.py listen --port 8765 --video
    python chat_app.py listen --port 8765 --audio
    python chat_app.py listen --port 8765 --video --audio

    # On the machine dialing in:
    python chat_app.py connect --onion xyikvsf3e55r....onion --port 80
    python chat_app.py connect --onion xyikvsf3e55r....onion --port 80 --video --audio

    While in video mode, a window titled "peer video" shows the incoming feed.
    Press 'q' in that window, or type /quit in the terminal, to end the call.
    Audio (mic capture + speaker playback) runs quietly in the background —
    there's no separate UI for it, just talk and listen.
"""

import argparse
import queue
import socket
import struct
import sys
import threading
import time
PRINT_LOCK = threading.Lock()

try:
    import socks  # PySocks — only required for connect mode
except ImportError:
    socks = None

TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9050  # default local Tor SOCKS5 port

MSG_TEXT = b"T"
MSG_VIDEO = b"V"
MSG_AUDIO = b"A"


# --------------------------------------------------------------------------
# Framed protocol helpers
# --------------------------------------------------------------------------

def send_framed(sock, sock_lock, msgtype, payload):
    """Send one length-prefixed frame. Thread-safe via sock_lock, since both
    the text sender and the video sender may write to the same socket."""
    header = msgtype + struct.pack(">I", len(payload))
    with sock_lock:
        sock.sendall(header + payload)


def recv_exact(sock, n):
    """Read exactly n bytes, or return None if the connection closes first."""
    buf = bytearray(n)
    view = memoryview(buf)
    pos = 0
    while pos < n:
        try:
            nbytes = sock.recv_into(view[pos:], n - pos)
        except OSError:
            return None
        if nbytes == 0:
            return None
        pos += nbytes
    return bytes(buf)


def read_frame(sock):
    """Read one [type][length][payload] frame. Returns (type, payload) or None."""
    header = recv_exact(sock, 5)
    if header is None:
        return None
    msgtype = header[0:1]
    length = struct.unpack(">I", header[1:5])[0]
    payload = recv_exact(sock, length) if length else b""
    if length and payload is None:
        return None
    return msgtype, payload


# --------------------------------------------------------------------------
# Text chat
# --------------------------------------------------------------------------

def recv_loop(sock, label, video_queue, audio_queue, stop_event):
    """Continuously read frames from the socket; print text, queue video/audio."""
    while not stop_event.is_set():
        frame = read_frame(sock)
        if frame is None:
            print(f"\n[{label}] connection closed by peer.")
            stop_event.set()
            break
        msgtype, payload = frame
        if msgtype == MSG_TEXT:
            text = payload.decode(errors="replace")
            with PRINT_LOCK:
                # \033[2K clears the ENTIRE current line before printing,
                # instead of just moving the cursor back to column 0 (\r).
                # This stops leftover fragments of whatever you were
                # mid-typing from being stranded on screen.
                print(f"\033[2K\r{label}: {text}\nyou: ", end="", flush=True)
        elif msgtype == MSG_VIDEO:
            if video_queue is not None:
                # Keep only the freshest frame — drop stale ones so video
                # doesn't fall further and further behind over a slow link.
                try:
                    while True:
                        video_queue.get_nowait()
                except queue.Empty:
                    pass
                video_queue.put(payload)
        elif msgtype == MSG_AUDIO:
            if audio_queue is not None:
                # Unlike video, keep a short run of chunks (a small jitter
                # buffer) rather than only the latest one — dropping every
                # chunk but the newest makes audio sound choppy/garbled.
                # If the buffer fills up (peer is consistently ahead of what
                # we can play back), drop the oldest chunk to bound latency.
                try:
                    audio_queue.put_nowait(payload)
                except queue.Full:
                    try:
                        audio_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        audio_queue.put_nowait(payload)
                    except queue.Full:
                        pass
        # unknown frame types are silently ignored (forward-compatible)


def send_loop(sock, sock_lock, stop_event):
    """Read from stdin and send each line to the peer as a text frame."""
    while not stop_event.is_set():
        try:
            text = input("you: ")
        except (EOFError, KeyboardInterrupt):
            break
        if text.strip() == "/quit":
            break
        try:
            send_framed(sock, sock_lock, MSG_TEXT, text.encode())
        except OSError:
            with PRINT_LOCK:
                print("[!] Failed to send — connection may be closed.")
            break
    stop_event.set()
    try:
        sock.close()
    except OSError:
        pass


# --------------------------------------------------------------------------
# Video call
# --------------------------------------------------------------------------

"""
Optimized video capture/display loops for real-time video exchange.

Key changes vs. the original:

CAPTURE SIDE
1. Ask the camera to natively capture at (width, height) instead of grabbing
   full-res frames and software-resizing every single one with cv2.resize.
   This is usually the single biggest CPU cost in the old loop.
2. Set CAP_PROP_BUFFERSIZE=1 so the OS/driver doesn't queue up several stale
   frames internally -- a very common hidden source of "lag" that creeps in
   over time even though your own loop looks fine.
3. Request MJPG FOURCC -- most USB webcams natively produce MJPEG, which is
   far cheaper to pull off the bus/driver than raw YUYV.
4. Decouple encoding from sending. In the original code, cap.read() ->
   encode -> send_framed() all happened in one line, so if the socket send
   blocked (slow/congested network), it stalled the camera capture itself,
   compounding lag. Now capture+encode runs in the main loop and hands the
   *latest* encoded frame to a single-slot mailbox (queue.Queue(maxsize=1)).
   A separate sender thread drains it and calls send_framed(). If the sender
   falls behind, the old unsent frame is dropped, not queued -- for live
   video, showing the newest frame late is much better than showing every
   frame increasingly late.
5. Skip the JPEG "optimize" pass (slow Huffman-table search) since it's not
   worth the CPU for real-time streaming quality.

DISPLAY SIDE
1. Drain the queue and keep only the newest frame before decoding/rendering.
   If frames arrive faster than they're displayed (e.g. after a hiccup), the
   original code would slowly render through a backlog, drifting further and
   further behind live. Now the display always shows the most recent frame
   and silently drops any older ones still sitting in the queue.

NOTE: the same "drop old, keep newest" discipline should be applied on the
receiving/network thread that feeds `video_queue` -- construct it with
`queue.Queue(maxsize=1)` and use the same full()->get_nowait()->put_nowait()
pattern shown below when pushing frames into it, otherwise you've just moved
the backlog one hop earlier.
"""



def video_capture_loop(sock, sock_lock, stop_event, cam_index, width, height, fps, quality):
    """Capture webcam frames, JPEG-encode them, and send as video frames."""
    try:
        import cv2
    except ImportError:
        print("[!] opencv-python is required for --video. Install with:")
        print("    pip install opencv-python numpy --break-system-packages")
        stop_event.set()
        return

    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        print(f"[!] Could not open camera index {cam_index}.")
        stop_event.set()
        return

    # Let the camera do the downscaling in hardware/driver instead of us
    # doing cv2.resize() on every single frame.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps > 0:
        cap.set(cv2.CAP_PROP_FPS, fps)
    # Minimize internal driver buffering so we always read the freshest frame.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    # Most webcams natively speak MJPG -- cheaper to pull than raw YUYV.
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    # Some backends ignore the requested size -- only resize if we have to.
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or width
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or height
    needs_resize = (actual_w, actual_h) != (width, height)

    encode_params = [
        int(cv2.IMWRITE_JPEG_QUALITY), quality,
        int(cv2.IMWRITE_JPEG_OPTIMIZE), 0,  # skip the slow optimal-Huffman pass
    ]
    interval = 1.0 / fps if fps > 0 else 0.1

    # Single-slot mailbox: the sender thread only ever sees the newest frame,
    # so a slow/blocked socket can never stall the camera capture loop.
    outbox = queue.Queue(maxsize=1)

    def sender():
        while not stop_event.is_set():
            try:
                data = outbox.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                send_framed(sock, sock_lock, MSG_VIDEO, data)
            except OSError:
                stop_event.set()
                return

    sender_thread = threading.Thread(target=sender, daemon=True)
    sender_thread.start()

    try:
        while not stop_event.is_set():
            start = time.time()
            ok, frame = cap.read()
            if not ok:
                continue
            if needs_resize:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
            ok, buf = cv2.imencode(".jpg", frame, encode_params)
            if not ok:
                continue
            data = buf.tobytes()

            # Drop any previous unsent frame rather than blocking on it --
            # the newest frame is always more useful than a stale queued one.
            if outbox.full():
                try:
                    outbox.get_nowait()
                except queue.Empty:
                    pass
            outbox.put_nowait(data)

            elapsed = time.time() - start
            remaining = interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
    finally:
        stop_event.set()
        cap.release()
        sender_thread.join(timeout=1)


def video_display_loop(video_queue, stop_event):
    """Show incoming video frames. Runs on the MAIN thread — OpenCV's GUI
    calls (imshow/waitKey) are not reliably thread-safe on every platform
    (notably macOS), so this loop must not be backgrounded."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return

    window_name = "peer video"
    while not stop_event.is_set():
        try:
            payload = video_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        # Drain any frames that piled up while we were decoding/rendering
        # the last one, keeping only the newest. This is what stops the
        # display from slowly drifting behind live video.
        while True:
            try:
                payload = video_queue.get_nowait()
            except queue.Empty:
                break

        arr = np.frombuffer(payload, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        cv2.imshow(window_name, img)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            stop_event.set()
            break
    cv2.destroyAllWindows()


# --------------------------------------------------------------------------
# Audio call
# --------------------------------------------------------------------------

_OPUS_VALID_FRAME_MS = (2.5, 5, 10, 20, 40, 60)


def _require_opus(sample_rate, chunk_ms):
    """Import opuslib and validate that (sample_rate, chunk_ms) form a
    legal Opus frame. Exits loudly on failure rather than falling back to
    raw PCM, since a silent per-side fallback would mean one peer sends
    Opus and the other expects raw PCM -- garbled audio with no clear error."""
    try:
        import opuslib
    except ImportError:
        print("[!] opuslib is required for --audio. Install with:")
        print("    pip install opuslib --break-system-packages")
        print("    (also requires the system 'libopus' library, e.g.")
        print("     'apt install libopus0' or 'brew install opus')")
        return None
    if chunk_ms not in _OPUS_VALID_FRAME_MS:
        print(f"[!] --audio-chunk-ms must be one of {_OPUS_VALID_FRAME_MS} for Opus, got {chunk_ms}")
        return None
    if sample_rate not in (8000, 12000, 16000, 24000, 48000):
        print(f"[!] --sample-rate must be one of 8000/12000/16000/24000/48000 for Opus, got {sample_rate}")
        return None
    return opuslib


def audio_capture_loop(sock, sock_lock, stop_event, sample_rate, chunk_ms, input_device):
    """Capture mic audio, Opus-encode it, and send as compressed audio frames."""
    try:
        import sounddevice as sd
    except ImportError:
        print("[!] sounddevice is required for --audio. Install with:")
        print("    pip install sounddevice numpy --break-system-packages")
        stop_event.set()
        return

    opuslib = _require_opus(sample_rate, chunk_ms)
    if opuslib is None:
        stop_event.set()
        return
    encoder = opuslib.Encoder(sample_rate, 1, opuslib.APPLICATION_VOIP)

    frames_per_chunk = max(1, int(sample_rate * chunk_ms / 1000))
    try:
        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frames_per_chunk,
            device=input_device,
        )
        stream.start()
    except Exception as e:
        print(f"[!] Could not open microphone: {e}")
        stop_event.set()
        return
    try:
        while not stop_event.is_set():
            try:
                data, _overflowed = stream.read(frames_per_chunk)
            except Exception:
                break
            try:
                encoded = encoder.encode(data.tobytes(), frames_per_chunk)
            except Exception:
                continue
            try:
                send_framed(sock, sock_lock, MSG_AUDIO, encoded)
            except OSError:
                break
    finally:
        stream.stop()
        stream.close()


def audio_playback_loop(audio_queue, stop_event, sample_rate, output_device, chunk_ms=40):
    """Pull received Opus-encoded audio chunks off the queue, decode, and
    play them out the speakers. Runs as a background thread — unlike video,
    audio playback has no GUI component so it doesn't need to be on the
    main thread."""
    try:
        import sounddevice as sd
        import numpy as np
    except ImportError:
        # Capture loop already printed the install instructions if needed.
        return

    opuslib = _require_opus(sample_rate, chunk_ms)
    if opuslib is None:
        stop_event.set()
        return
    decoder = opuslib.Decoder(sample_rate, 1)
    frames_per_chunk = max(1, int(sample_rate * chunk_ms / 1000))

    try:
        stream = sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16", device=output_device)
        stream.start()
    except Exception as e:
        print(f"[!] Could not open speaker output: {e}")
        return
    try:
        while not stop_event.is_set():
            try:
                payload = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                pcm = decoder.decode(payload, frames_per_chunk)
            except Exception:
                continue
            arr = np.frombuffer(pcm, dtype=np.int16)
            try:
                stream.write(arr)
            except Exception:
                pass
    finally:
        stream.stop()
        stream.close()


# --------------------------------------------------------------------------
# Chat orchestration
# --------------------------------------------------------------------------

def run_chat(
    sock,
    label,
    video=False,
    cam_index=0,
    width=160,
    height=120,
    fps=8,
    quality=40,
    audio=False,
    sample_rate=16000,
    audio_chunk_ms=40,
    input_device=None,
    output_device=None,
):
    """Start reader/writer (and optional video/audio) threads and block
    until the chat ends."""
    print("[+] Connected. Type messages and press Enter. Type /quit to exit.\n")

    stop_event = threading.Event()
    sock_lock = threading.Lock()
    video_queue = queue.Queue(maxsize=1) if video else None
    # ~ (audio_queue_max * audio_chunk_ms) worth of buffered audio, e.g.
    # 20 * 40ms = 800ms of headroom to absorb Tor's jitter before dropping.
    audio_queue = queue.Queue(maxsize=20) if audio else None

    t_recv = threading.Thread(target=recv_loop, args=(sock, label, video_queue, audio_queue, stop_event), daemon=True)
    t_recv.start()

    if audio:
        t_audio_cap = threading.Thread(
            target=audio_capture_loop,
            args=(sock, sock_lock, stop_event, sample_rate, audio_chunk_ms, input_device),
            daemon=True,
        )
        t_audio_cap.start()

        t_audio_play = threading.Thread(
            target=audio_playback_loop,
            args=(audio_queue, stop_event, sample_rate, output_device, audio_chunk_ms),
            daemon=True,
        )
        t_audio_play.start()

        print("[+] Audio call enabled — speak and listen normally, no extra window needed.\n")

    if video:
        t_cap = threading.Thread(
            target=video_capture_loop,
            args=(sock, sock_lock, stop_event, cam_index, width, height, fps, quality),
            daemon=True,
        )
        t_cap.start()

        t_send = threading.Thread(target=send_loop, args=(sock, sock_lock, stop_event), daemon=True)
        t_send.start()

        print("[+] Video call enabled. A 'peer video' window will open shortly.")
        print("    Press 'q' in that window, or type /quit here, to end the call.\n")

        # Display must run on the main thread.
        video_display_loop(video_queue, stop_event)
        stop_event.set()
    else:
        send_loop(sock, sock_lock, stop_event)
        stop_event.set()

    print("[+] Chat ended.")


def do_listen(port, video, cam_index, width, height, fps, quality, audio, sample_rate, audio_chunk_ms, input_device, output_device):
    """
    Bind a local TCP listener. Map this port in your torrc, e.g.:
        HiddenServicePort 80 127.0.0.1:<port>
    so it becomes reachable as your onion address.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(1)
    print(f"[+] Listening on 127.0.0.1:{port} (map this in torrc to your onion address)")
    print("[+] Waiting for an incoming connection through Tor...")
    conn, addr = server.accept()
    print(f"[+] Incoming connection accepted (source: {addr})")

    # Disable Nagle's algorithm on the actual chat connection (not the
    # listening socket) -- same reasoning as the connect side: avoids the OS
    # buffering small frame writes for tens of milliseconds before sending.
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    run_chat(
        conn,
        "peer",
        video=video,
        cam_index=cam_index,
        width=width,
        height=height,
        fps=fps,
        quality=quality,
        audio=audio,
        sample_rate=sample_rate,
        audio_chunk_ms=audio_chunk_ms,
        input_device=input_device,
        output_device=output_device,
    )


def do_connect(onion_address, port, video, cam_index, width, height, fps, quality, audio, sample_rate, audio_chunk_ms, input_device, output_device):
    """
    Dial out to a remote .onion address through the local Tor SOCKS5 proxy.
    Requires Tor to be running locally with its SOCKS port open (default 9050).
    """
    if socks is None:
        print("[!] PySocks is required for connect mode. Install it with:")
        print("    pip install PySocks --break-system-packages")
        sys.exit(1)
    sock = socks.socksocket()
    sock.set_proxy(socks.SOCKS5, TOR_SOCKS_HOST, TOR_SOCKS_PORT, rdns=True)
    print(f"[+] Connecting to {onion_address}:{port} via Tor SOCKS5 ({TOR_SOCKS_HOST}:{TOR_SOCKS_PORT})...")
    print("[+] This can take 10-30 seconds over Tor — please wait.")
    try:
        sock.connect((onion_address, port))
    except Exception as e:
        print(f"[!] Failed to connect: {e}")
        print("    - Is Tor running locally with its SOCKS proxy on port 9050?")
        print("    - Is the remote peer's listener + hidden service actually up?")
        print("    - Double-check the onion address and port.")
        sys.exit(1)

    # Disable Nagle's algorithm: without this, small frame headers/payloads
    # can sit buffered for tens of milliseconds waiting to coalesce with
    # more data before the OS actually sends them -- pure added latency for
    # a real-time protocol that already sends small, frequent frames.
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    run_chat(
        sock,
        "peer",
        video=video,
        cam_index=cam_index,
        width=width,
        height=height,
        fps=fps,
        quality=quality,
        audio=audio,
        sample_rate=sample_rate,
        audio_chunk_ms=audio_chunk_ms,
        input_device=input_device,
        output_device=output_device,
    )


def add_video_args(p):
    p.add_argument("--video", action="store_true", help="Enable webcam video call alongside text chat.")
    p.add_argument("--cam-index", type=int, default=0, help="Camera device index (default: 0).")
    p.add_argument("--width", type=int, default=160, help="Sent video frame width (default: 160). Keep small over Tor.")
    p.add_argument("--height", type=int, default=120, help="Sent video frame height (default: 120).")
    p.add_argument("--fps", type=float, default=8, help="Target send frame rate (default: 8). Keep low over Tor.")
    p.add_argument("--quality", type=int, default=40, help="JPEG quality 1-100 (default: 40). Lower = smaller/faster.")


def add_audio_args(p):
    p.add_argument("--audio", action="store_true", help="Enable microphone/speaker audio call alongside text chat.")
    p.add_argument("--sample-rate", type=int, default=16000, help="Audio sample rate in Hz (default: 16000). Keep low over Tor.")
    p.add_argument("--audio-chunk-ms", type=int, default=40, help="Audio chunk size in milliseconds (default: 40). Smaller = lower latency but more per-chunk overhead.")
    p.add_argument("--input-device", type=int, default=None, help="Input (microphone) device index. Default: system default device.")
    p.add_argument("--output-device", type=int, default=None, help="Output (speaker) device index. Default: system default device.")


def main():
    parser = argparse.ArgumentParser(description="Direct Tor P2P chat + video + audio (no WebRTC).")
    sub = parser.add_subparsers(dest="mode", required=True)

    listen_p = sub.add_parser("listen", help="Wait for an incoming connection (host side).")
    listen_p.add_argument("--port", type=int, default=8765, help="Local port to bind (map in torrc).")
    add_video_args(listen_p)
    add_audio_args(listen_p)

    connect_p = sub.add_parser("connect", help="Dial out to a peer's onion address.")
    connect_p.add_argument("--onion", required=True, help="Peer's onion address, e.g. xyikvsf....onion")
    connect_p.add_argument("--port", type=int, default=80, help="Port exposed on their hidden service.")
    add_video_args(connect_p)
    add_audio_args(connect_p)

    args = parser.parse_args()

    if args.mode == "listen":
        do_listen(
            args.port,
            args.video,
            args.cam_index,
            args.width,
            args.height,
            args.fps,
            args.quality,
            args.audio,
            args.sample_rate,
            args.audio_chunk_ms,
            args.input_device,
            args.output_device,
        )
    elif args.mode == "connect":
        do_connect(
            args.onion,
            args.port,
            args.video,
            args.cam_index,
            args.width,
            args.height,
            args.fps,
            args.quality,
            args.audio,
            args.sample_rate,
            args.audio_chunk_ms,
            args.input_device,
            args.output_device,
        )


if __name__ == "__main__":
    main()