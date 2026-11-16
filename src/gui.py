try:
    import configs
except:
    import configs_build as configs

COC_BOT_GUI = None

def find_open_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def _want_qt():
    """The v4 Qt window unless the user chose the classic web window (or PySide6 is missing)."""
    try:
        import settings
        if settings.load_app().get("ui", "qt") == "web": return False
        import PySide6  # noqa: F401
        return True
    except Exception:
        return False

def run_gui(server_port, pipe, debug=False):
    if _want_qt():
        try:
            from qt_ui.app import run_qt
            run_qt(server_port, pipe, debug)
            return
        except Exception:
            import traceback
            traceback.print_exc() # fall back to the classic window below
    import sys, webview
    
    url = f"http://127.0.0.1:{server_port}"
    window = webview.create_window(
        "CoC Bot",
        url=url,
        width=1320,
        height=860,
        min_size=(980, 680),
        resizable=True,
        background_color="#0d1730",
    )
    
    def on_closed():
        pipe.send(-1)
    
    window.events.closed += on_closed
    webview.start(debug=debug)

class GUI:
    def __init__(self, id=None, debug=False):
        from multiprocessing import Process, Pipe
        from gui_server.gui_server import start_server
        
        self.debug = debug
        self.id = id
        parent_conn, child_conn = Pipe()
        self.pipe = parent_conn
        self.server_port = find_open_port()
        self.server_proc = Process(target=start_server, args=(child_conn, self.server_port, id, False,))
        self.server_proc.start()
        self.window_proc = Process(target=run_gui, args=(self.server_port, child_conn, self.debug))
    
    def start(self):
        self.window_proc.start()

    def stop(self):
        if self.server_proc.is_alive():
            self.server_proc.terminate()
            self.server_proc.join()
        if self.window_proc.is_alive():
            self.window_proc.terminate()
            self.window_proc.join()

def init_gui(id=None, debug=False):
    global COC_BOT_GUI
    COC_BOT_GUI = GUI(id, debug=debug)
    COC_BOT_GUI.start()
    return COC_BOT_GUI.pipe

def get_gui():
    return COC_BOT_GUI

if __name__ == "__main__":
    # running gui.py directly used to open only the window (the "start bot" button then did nothing):
    # start the full program with its window instead
    import sys
    from multiprocessing import freeze_support
    freeze_support()
    if "--gui" not in sys.argv: sys.argv.append("--gui")
    from launch import launch
    launch()
