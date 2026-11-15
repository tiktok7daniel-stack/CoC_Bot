from utils import *
try:
    from configs import *
except:
    from configs_build import *
from upgrader import Upgrader
from attacker import Attacker

class CoC_Bot:
    def __init__(self):
        self.upgrader = Upgrader()
        self.attacker = Attacker()
    
    def run(self):
        import time
        
        consecutive_errors = 0
        while True:
            try:
                if not online():
                    time.sleep(1)
                    continue

                if not running():
                    time.sleep(10)
                    continue
                
                started, res = start_coc(detailed=True)
                if started:
                    update_status("now")
                    cycle_start = time.monotonic()
                    
                    Task_Handler.get_exclusions()
                    exclude_home_base = Task_Handler.excluded("home_base", use_cached=True)
                    exclude_home_lab = Task_Handler.excluded("home_lab", use_cached=True)
                    exclude_pets = Task_Handler.excluded("pet_house", use_cached=True)
                    skip_home_base_upgrades = exclude_home_base and exclude_home_lab and exclude_pets
                    exclude_home_attacks = Task_Handler.excluded("home_attacks", use_cached=True)
                    
                    exclude_builder_base = Task_Handler.excluded("builder_base", use_cached=True)
                    exclude_builder_lab = Task_Handler.excluded("builder_lab", use_cached=True)
                    skip_builder_base_upgrades = exclude_builder_base and exclude_builder_lab
                    exclude_builder_attacks = Task_Handler.excluded("builder_attacks", use_cached=True)
                    
                    # Check home base
                    if not skip_home_base_upgrades or not exclude_home_attacks:
                        to_home_base(ref_cache=True)
                    
                    if not skip_home_base_upgrades:
                        logger.info("Upgrading home base")
                        self.upgrader.run_home_base(exclude_home_base, exclude_home_lab, exclude_pets)
                    if not exclude_home_attacks:
                        logger.info("Attacking home base")
                        self.attacker.run_home_base(restart=not skip_home_base_upgrades or not skip_builder_base_upgrades)
                    
                    # Check builder base
                    if not skip_builder_base_upgrades or not exclude_builder_attacks:
                        to_builder_base(ref_cache=True)
                    
                    if not skip_builder_base_upgrades:
                        logger.info("Upgrading builder base")
                        self.upgrader.collect_builder_attack_elixir()
                        self.upgrader.run_builder_base(exclude_builder_base, exclude_builder_lab)
                    if not exclude_builder_attacks:
                        logger.info("Attacking builder base")
                        self.attacker.run_builder_base()
                    
                    to_home_base()
                    stop_coc(sleep=configs.SUSPEND_EMULATOR_ON_IDLE)
                    update_status(time.time())
                    logger.info(f"Cycle finished in {time.monotonic() - cycle_start:.0f}s")
                    consecutive_errors = 0
                elif res == "error":
                    update_status("error")
                
                time.sleep(60 * CHECK_INTERVAL)
            
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                consecutive_errors += 1
                logger.exception(f"CoC_Bot.run (error #{consecutive_errors} in a row):")
                if consecutive_errors == 3:
                    send_notification(f"Bot failed 3 times in a row, last error: {type(e).__name__}: {e}")
                try: stop_coc()
                except (KeyboardInterrupt, SystemExit): raise
                except Exception: logger.exception("CoC_Bot.run: stop_coc failed")
                update_status("error")
                # retry quickly after a one-off glitch, back off when something is persistently broken
                wait = 60 if consecutive_errors == 1 else 60 * CHECK_INTERVAL * min(consecutive_errors - 1, 6)
                time.sleep(wait)
