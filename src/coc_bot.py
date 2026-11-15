from utils import *
try:
    from configs import *
except:
    from configs_build import *
import utils as _utils
import settings as bot_settings
import stats
from upgrader import Upgrader
from attacker import Attacker

class CoC_Bot:
    def __init__(self):
        self.upgrader = Upgrader()
        self.attacker = Attacker()
        self.cycle_count = 0
        self.upgrader.on_upgrade = lambda kind, name: stats.record(_utils.INSTANCE_ID, "upgrade", kind=kind, name=name)

    def load_settings(self):
        """Re-read the account's GUI settings every cycle so changes apply without a restart."""
        try:
            s = bot_settings.load(_utils.INSTANCE_ID)
            bot_settings.apply(s)
        except Exception:
            logger.exception("CoC_Bot.load_settings: using previous settings")
            s = getattr(self, "settings", None) or bot_settings.default_settings()
        Task_Handler.cache_valid = False
        self.settings = s
        return s

    def read_and_record_resources(self, builder_base=False):
        res = read_resources(builder_base=builder_base)
        if res is not None and not builder_base:
            stats.record(_utils.INSTANCE_ID, "resources", **res)
            logger.info(f"Resources: gold={res['gold']} elixir={res['elixir']} dark={res['dark']}")
        return res

    def attack_with_loot(self, base, attack_fn):
        """Run one attack and record the loot as the storage difference before/after."""
        builder = base == "builder"
        before = self.read_and_record_resources(builder_base=builder)
        attack_fn()
        try:
            (to_builder_base if builder else to_home_base)()
        except Exception:
            pass
        after = self.read_and_record_resources(builder_base=builder)
        loot = {}
        for k in ("gold", "elixir", "dark"):
            b, a = (before or {}).get(k), (after or {}).get(k)
            loot[k] = max(0, a - b) if a is not None and b is not None else 0
        stats.record(_utils.INSTANCE_ID, "attack", base=base, **loot)
        logger.info(f"Attack ({base}) loot: gold={loot['gold']} elixir={loot['elixir']} dark={loot['dark']}")

    def run(self):
        import time

        stats.record(_utils.INSTANCE_ID, "session_start")
        consecutive_errors = 0
        while True:
            try:
                s = self.load_settings()

                if not online():
                    time.sleep(1)
                    continue

                if not running():
                    time.sleep(10)
                    continue

                if not bot_settings.in_schedule(s):
                    update_status("scheduled")
                    time.sleep(60)
                    continue

                started, res = start_coc(detailed=True)
                if started:
                    update_status("now")
                    cycle_start = time.monotonic()
                    self.cycle_count += 1

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

                    # Wall / budget settings for this cycle
                    walls = s["walls"]
                    wall_turn = walls["enabled"] and self.cycle_count % max(1, int(walls["every_cycles"])) == 0
                    self.upgrader.wall_budget = max(0, int(walls["max_per_run"])) if wall_turn else 0
                    self.upgrader.budget = s["budget"] if s["budget"]["enabled"] else None

                    # Check home base
                    if not skip_home_base_upgrades or not exclude_home_attacks:
                        to_home_base(ref_cache=True)
                        self.read_and_record_resources()

                    if not skip_home_base_upgrades:
                        logger.info("Upgrading home base")
                        self.upgrader.run_home_base(exclude_home_base, exclude_home_lab, exclude_pets)
                    if not exclude_home_attacks:
                        n = max(1, int(s["attack"]["home_attacks_per_cycle"]))
                        for i in range(n):
                            if not running(): break
                            logger.info(f"Attacking home base ({i + 1}/{n})")
                            last = i == n - 1
                            # always restart (not just stop) the game so the loot can be read afterwards
                            self.attack_with_loot("home", lambda: self.attacker.run_home_base(restart=True))
                            # optionally spend the new loot on walls between farming attacks
                            if not last and walls["enabled"] and walls["during_farming"] and not exclude_home_base:
                                to_home_base()
                                self.upgrader.wall_budget = max(0, int(walls["max_per_run"]))
                                self.upgrader.run_home_base(False, True, True)

                    # Check builder base
                    if not skip_builder_base_upgrades or not exclude_builder_attacks:
                        to_builder_base(ref_cache=True)

                    if not skip_builder_base_upgrades:
                        logger.info("Upgrading builder base")
                        self.upgrader.collect_builder_attack_elixir()
                        self.upgrader.run_builder_base(exclude_builder_base, exclude_builder_lab)
                    if not exclude_builder_attacks:
                        n = max(1, int(s["attack"]["builder_attacks_per_cycle"]))
                        for i in range(n):
                            if not running(): break
                            logger.info(f"Attacking builder base ({i + 1}/{n})")
                            self.attack_with_loot("builder", self.attacker.run_builder_base)

                    to_home_base()
                    stop_coc(sleep=configs.SUSPEND_EMULATOR_ON_IDLE)
                    update_status(time.time())
                    seconds = time.monotonic() - cycle_start
                    stats.record(_utils.INSTANCE_ID, "cycle", seconds=round(seconds))
                    logger.info(f"Cycle finished in {seconds:.0f}s")
                    consecutive_errors = 0
                elif res == "error":
                    update_status("error")

                time.sleep(60 * configs.CHECK_INTERVAL)

            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                consecutive_errors += 1
                logger.exception(f"CoC_Bot.run (error #{consecutive_errors} in a row):")
                stats.record(_utils.INSTANCE_ID, "error", message=f"{type(e).__name__}: {e}")
                if consecutive_errors == 3:
                    send_notification(f"Bot failed 3 times in a row, last error: {type(e).__name__}: {e}")
                try: stop_coc()
                except (KeyboardInterrupt, SystemExit): raise
                except Exception: logger.exception("CoC_Bot.run: stop_coc failed")
                update_status("error")
                # retry quickly after a one-off glitch, back off when something is persistently broken
                wait = 60 if consecutive_errors == 1 else 60 * configs.CHECK_INTERVAL * min(consecutive_errors - 1, 6)
                time.sleep(wait)
