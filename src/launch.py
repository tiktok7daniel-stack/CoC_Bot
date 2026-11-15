try:
    from configs import *
except:
    from configs_build import *

MULTI_INSTANCE_STAGGER = globals().get("MULTI_INSTANCE_STAGGER", 20) # seconds between instance launches

def gui_disable_sleep():
    import time, utils
    utils.disable_sleep()
    while True: time.sleep(1)

def launch_proc(args):
    import settings
    settings.apply_app_settings() # accounts / emulator chosen in the GUI (before utils picks the emulator)
    from log import enable_logging
    from utils import parse_args, init_instance
    from coc_bot import CoC_Bot
    
    parse_args(args.debug, args.id, args.gui, args.gui_port)
    enable_logging(args.id) # first, so problems while starting the emulator are in the log
    from log import logger
    import time
    from utils import install_error_reporter, start_capture_service, start_record_service, update_status, preflight
    logger.info("Bot starting: preparing the emulator")
    for attempt in range(1, 1000):
        try:
            init_instance(args.id)
            break
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            if attempt == 1: logger.exception("Bot start failed (details):")
            logger.error(f"Bot start failed: {type(e).__name__}: {e}")
            update_status("error")
            time.sleep(min(60, 10 * attempt))
    install_error_reporter()
    start_capture_service()
    preflight()
    bot = CoC_Bot()
    bot.run()

def cmd_launch(args):
    import utils
    if args.ids is not None and len(args.ids) > 1:
        return multi_launch(args)
    if args.ids: args.id = args.ids[0]
    if DISABLE_DEVICE_SLEEP: utils.disable_sleep()
    launch_proc(args)

def multi_launch(args):
    """Run one bot process per account in parallel and restart any that crash."""
    import time
    from multiprocessing import Process
    from copy import deepcopy

    sleep_proc = None
    if DISABLE_DEVICE_SLEEP:
        sleep_proc = Process(target=gui_disable_sleep, daemon=True)
        sleep_proc.start()

    procs, restarts, restart_at = {}, {}, {}

    def spawn(id):
        a = deepcopy(args)
        a.id, a.ids, a.all = id, None, False
        p = Process(target=launch_proc, args=(a,), name=f"CoC_Bot[{id}]")
        p.start()
        p._started_at = time.time()
        procs[id] = p
        print(f"[launcher] started instance '{id}' (pid {p.pid})")

    try:
        for i, id in enumerate(args.ids):
            if i > 0: time.sleep(MULTI_INSTANCE_STAGGER) # avoid booting every emulator at once
            spawn(id)
        while True:
            time.sleep(5)
            now = time.time()
            for id, p in list(procs.items()):
                if p.is_alive():
                    # healthy for an hour -> forget earlier crashes
                    if id in restarts and now - restart_at.get(id, now) > 3600: restarts.pop(id)
                    continue
                if id not in restart_at or restart_at[id] <= getattr(p, "_started_at", 0):
                    n = restarts.get(id, 0)
                    delay = min(30 * 2 ** n, 900)
                    restart_at[id] = now + delay
                    restarts[id] = n + 1
                    print(f"[launcher] instance '{id}' exited (code {p.exitcode}), restarting in {delay}s")
                elif now >= restart_at[id]:
                    spawn(id) # other instances keep being monitored while this one waits
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        if sleep_proc is not None: sleep_proc.terminate()
        for p in procs.values():
            if p.is_alive():
                p.terminate()
                p.join(10)

def gui_launch(args):
    import time
    from multiprocessing import Process
    from gui import init_gui, get_gui
    from copy import deepcopy
    
    procs = {}
    preset = ([args.id] if args.id is not None else []) + [i for i in (args.ids or []) if i != args.id]
    pipe = init_gui(preset)
    args.gui_port = get_gui().server_port
    
    sleep_proc = None
    if DISABLE_DEVICE_SLEEP:
        sleep_proc = Process(target=gui_disable_sleep, daemon=True)
        sleep_proc.start()

    if args.id is not None:
        p = Process(target=launch_proc, args=(args,), daemon=True)
        p.start()
        procs[args.id] = p
    for i, id in enumerate(args.ids or []): # --all / --ids: auto-start these accounts
        if id in procs: continue
        if procs: time.sleep(MULTI_INSTANCE_STAGGER)
        args_copy = deepcopy(args)
        args_copy.id, args_copy.ids, args_copy.all = id, None, False
        p = Process(target=launch_proc, args=(args_copy,), daemon=True)
        p.start()
        procs[id] = p
    try:
        while True:
            data = pipe.recv()
            if data == -1: raise SystemExit
            action, id = data.get("action"), data.get("id")
            if action == "start":
                args_copy = deepcopy(args)
                args_copy.id = data.get("id")
                p = Process(target=launch_proc, args=(args_copy,))
                p.start()
                procs[id] = p
            elif action == "stop":
                p = procs.pop(id, None)
                if p and p.is_alive():
                    p.terminate()
                    p.join()
    except (EOFError, KeyboardInterrupt, SystemExit):
        get_gui().stop()
        pipe.close()
        if sleep_proc is not None: sleep_proc.terminate()
        for p in procs.values():
            if p and p.is_alive():
                p.terminate()
                p.join()

def launch():
    import settings
    settings.apply_app_settings()
    import utils
    args = utils.parse_args()
    if args.gui: gui_launch(args)
    else: cmd_launch(args)
