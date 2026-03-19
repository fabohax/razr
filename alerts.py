import subprocess


def send_desktop_alert(title: str, body: str, urgency: str = "critical"):
    """Envía notificación nativa de Ubuntu con notify-send."""
    try:
        subprocess.run(["notify-send", title, body, "-u", urgency, "-t", "15000"], check=False)
    except FileNotFoundError:
        raise RuntimeError("notify-send no encontrado. Instala libnotify-bin.")
    except Exception as e:
        raise RuntimeError(f"Error al ejecutar notify-send: {e}")


def play_sound(sound_file: str = None):
    """Reproduce un sonido para la alerta usando paplay o sox play."""
    if not sound_file:
        # beep de sistema si no hay archivo
        try:
            subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"], check=False)
            return
        except FileNotFoundError:
            pass

    # Si el archivo existe, tratar de reproducirlo.
    if sound_file:
        try:
            subprocess.run(["paplay", sound_file], check=False)
            return
        except FileNotFoundError:
            pass
        try:
            subprocess.run(["play", sound_file], check=False)
            return
        except FileNotFoundError:
            pass

    # Si no hay sonido, fallback a beep
    try:
        subprocess.run(["printf", "\a"], check=False)
    except Exception:
        pass
