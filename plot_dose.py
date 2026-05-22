"""
Live dose rate plot for the gamma probe.
Reads directly from COM6 and plots dose rate in real-time.
Run on Windows: python plot_dose.py
(Stop the serial_bridge.py first, or run this instead of the bridge)
"""
import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
import time
import winsound

PORT = "COM6"
BAUD = 9600
MAX_POINTS = 300  # 5 minutes at 1Hz
DOSE_THRESHOLD = 200.0  # µSv/h


def parse_message(line):
    """Parse probe message, return dose rate or None."""
    line = line.strip()
    if not line.startswith('$'):
        return None
    if '*' not in line:
        return None
    payload, _ = line.rsplit('*', 1)
    fields = payload[1:].split(',')
    if len(fields) != 4:
        return None
    try:
        return float(fields[3])
    except (ValueError, IndexError):
        return None


def main():
    # Connect directly to serial port
    try:
        ser = serial.Serial(PORT, BAUD, timeout=2)
    except serial.SerialException as e:
        print(f"ERROR: Cannot open {PORT}: {e}")
        print("Make sure serial_bridge.py is NOT running (it locks COM6)")
        return
    print(f"Connected to {PORT}. Plotting...")

    times = deque(maxlen=MAX_POINTS)
    doses = deque(maxlen=MAX_POINTS)
    start_time = time.time()

    fig, ax = plt.subplots(figsize=(10, 5))
    line_plot, = ax.plot([], [], 'g-', linewidth=1.5)
    threshold_line = ax.axhline(y=DOSE_THRESHOLD, color='r', linestyle='--', linewidth=1, label=f'Threshold ({DOSE_THRESHOLD} µSv/h)')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Dose Rate (µSv/h)')
    ax.set_title('Live Gamma Probe Dose Rate')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    alarm_text = ax.text(0.5, 0.9, '', transform=ax.transAxes, ha='center',
                         fontsize=16, fontweight='bold', color='red')
    last_beep = [0]

    def update(frame):
        try:
            raw = ser.read_until(b'\r').decode('ascii', errors='ignore')
            if raw:
                dose = parse_message(raw)
                if dose is not None:
                    t = time.time() - start_time
                    times.append(t)
                    doses.append(dose)

                    line_plot.set_data(list(times), list(doses))
                    ax.set_xlim(max(0, t - 300), t + 5)
                    ax.set_ylim(0, max(max(doses) * 1.2, DOSE_THRESHOLD * 1.1) + 0.5)

                    # Threshold alarm
                    if dose >= DOSE_THRESHOLD:
                        line_plot.set_color('red')
                        alarm_text.set_text(f'⚠ ALARM: {dose:.1f} µSv/h ⚠')
                        ax.set_title(f'⚠ DOSE ALARM — {dose:.1f} µSv/h')
                        # Audible beep (max once per 2 seconds)
                        if time.time() - last_beep[0] > 2:
                            winsound.Beep(1000, 2000)
                            last_beep[0] = time.time()
                    else:
                        line_plot.set_color('green')
                        alarm_text.set_text('')
                        ax.set_title(f'Live Gamma Probe Dose Rate — {dose:.1f} µSv/h')
        except Exception:
            pass
        return line_plot, alarm_text

    ani = animation.FuncAnimation(fig, update, interval=500, blit=False, cache_frame_data=False)
    plt.tight_layout()
    plt.show()

    ser.close()


if __name__ == "__main__":
    main()
