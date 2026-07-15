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
DOSE_THRESHOLD = 150.0  # µSv/h (0.15 mSv/h) — must match dose_threshold_usvh in gamma_probe.launch


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
    doses_avg = deque(maxlen=MAX_POINTS)
    avg_buffer = deque(maxlen=10)  # 10-second rolling average
    start_time = time.time()

    fig, ax = plt.subplots(figsize=(10, 5))
    line_plot, = ax.plot([], [], 'g-', linewidth=1, alpha=0.5, label='Raw (1 Hz)')
    line_avg, = ax.plot([], [], 'b-', linewidth=2.5, label='10s Average')
    threshold_line = ax.axhline(y=DOSE_THRESHOLD, color='r', linestyle='--', linewidth=1, label=f'Threshold ({DOSE_THRESHOLD} µSv/h)')
    ax.set_xlabel('Time (s)')
    ax.set_ylabel('Dose Rate (µSv/h)')
    ax.set_title('Live Gamma Probe Dose Rate')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)
    alarm_text = ax.text(0.5, 0.9, '', transform=ax.transAxes, ha='center',
                         fontsize=16, fontweight='bold', color='red')
    status_text = ax.text(0.98, 0.95, 'NOT ACTIVE', transform=ax.transAxes, ha='right',
                          fontsize=12, fontweight='bold', color='red',
                          bbox=dict(boxstyle='round,pad=0.3', facecolor='#ffcccc', edgecolor='red'))
    last_beep = [0]
    last_data_time = [0.0]  # track last successful data reception
    INACTIVE_TIMEOUT = 5  # seconds with no data before marking inactive

    def update(frame):
        try:
            raw = ser.read_until(b'\r').decode('ascii', errors='ignore')
            if raw:
                dose = parse_message(raw)
                if dose is not None:
                    last_data_time[0] = time.time()
                    t = time.time() - start_time
                    times.append(t)
                    doses.append(dose)

                    avg_buffer.append(dose)
                    avg = sum(avg_buffer) / len(avg_buffer)
                    doses_avg.append(avg)

                    line_plot.set_data(list(times), list(doses))
                    line_avg.set_data(list(times), list(doses_avg))
                    ax.set_xlim(max(0, t - 300), t + 5)
                    ax.set_ylim(0, max(max(doses) * 1.2, DOSE_THRESHOLD * 1.1) + 0.5)

                    # Threshold alarm (based on averaged dose)
                    if avg >= DOSE_THRESHOLD:
                        line_avg.set_color('red')
                        alarm_text.set_text(f'⚠ ALARM: avg {avg:.1f} µSv/h ⚠')
                        ax.set_title(f'⚠ DOSE ALARM — avg {avg:.1f} µSv/h')
                        # Audible beep (max once per 2 seconds)
                        if time.time() - last_beep[0] > 2:
                            winsound.Beep(1000, 2000)
                            last_beep[0] = time.time()
                    else:
                        line_avg.set_color('blue')
                        alarm_text.set_text('')
                        ax.set_title(f'Live Gamma Probe — {dose:.1f} µSv/h (avg {avg:.1f})')
        except Exception:
            pass

        # Update probe status indicator
        if last_data_time[0] > 0 and (time.time() - last_data_time[0]) < INACTIVE_TIMEOUT:
            status_text.set_text('ACTIVE')
            status_text.set_color('green')
            status_text.set_bbox(dict(boxstyle='round,pad=0.3', facecolor='#ccffcc', edgecolor='green'))
        else:
            status_text.set_text('NOT ACTIVE')
            status_text.set_color('red')
            status_text.set_bbox(dict(boxstyle='round,pad=0.3', facecolor='#ffcccc', edgecolor='red'))

        return line_plot, line_avg, alarm_text, status_text

    ani = animation.FuncAnimation(fig, update, interval=500, blit=False, cache_frame_data=False)
    plt.tight_layout()
    plt.show()

    ser.close()


if __name__ == "__main__":
    main()
