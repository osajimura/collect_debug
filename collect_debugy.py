#!/usr/bin/env python3
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import threading
import time

LOGFILE = "/scratch/pss.out"
MAX_SIZE = 335544320  # 320 MB
MAX_FILES = 3
USAGE_LIMIT = 80
WATCHDOG_TIMEOUT = 15  # Timeout threshold in seconds

# Shared thread-safe storage for cached WIDs
cached_wids = []

# Global debug flag
DEBUG = False

def log_debug(msg):
  """Print debug log if DEBUG flag is enabled."""
  if DEBUG:
    print(f"[DEBUG] {msg}", flush=True)


def run_cmd(cmd):
  """Helper function to execute a shell command."""
  try:
    log_debug(f"Calling {cmd}")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return res.stdout
  except Exception:
    return ""


def check_disk_usage():
  """Check /scratch disk usage (%) and exit if limit is reached."""
  output = run_cmd("df /scratch")
  lines = [line for line in output.strip().split("\n") if line]
  if len(lines) >= 2:
    fields = lines[-1].split()
    if len(fields) >= 5:
      usage_str = fields[4].replace("%", "")
      if usage_str.isdigit():
        usage = int(usage_str)
        if usage >= USAGE_LIMIT:
          now_str = datetime.datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y")
          log_msg = f"{now_str}: /scratch usage reached {usage}%. Exiting script to prevent disk full.\n"
          with open(LOGFILE, "a") as f:
            f.write(log_msg)
          sys.exit(1)


def rotate_logs():
  """Rotate log files if current LOGFILE exceeds MAX_SIZE."""
  if not os.path.isfile(LOGFILE):
    return

  try:
    size = os.path.getsize(LOGFILE)
  except OSError:
    return

  if size >= MAX_SIZE:
    for n in range(MAX_FILES - 1, 0, -1):
      next_num = n + 1
      src = f"{LOGFILE}.{n}"
      dst = f"{LOGFILE}.{next_num}"
      if os.path.isfile(src):
        try:
          shutil.move(src, dst)
        except OSError:
          pass

    try:
      shutil.move(LOGFILE, f"{LOGFILE}.1")
      open(LOGFILE, "a").close()
    except OSError:
      pass


def get_cvm_gid():
  """Extract VMX Cartel ID (GID) for NTNX VM using esxcli."""
  output = run_cmd("esxcli vm process list | grep -A3 '^NTNX'")
  match = re.search(r"VMX Cartel ID:\s*(\d+)", output)
  if match:
    gid = match.group(1)
    log_debug(f"Found CVM GID: {gid}")
    return gid
  log_debug("CVM GID not found")
  return ""


def initialize_wids(gid):
  """Fetch and cache WIDs associated with the GID once at startup."""
  ps_out = run_cmd("ps -j")
  wids = []
  for line in ps_out.splitlines():
    if gid in line:
      parts = line.split()
      if parts:
        wids.append(parts[0])

  if wids:
    global cached_wids
    cached_wids = wids
    log_debug(f"Initialized WIDs for GID {gid}: {cached_wids}")
  else:
    log_debug(f"No WIDs found for GID {gid}")


def dump_all_cvm_worlds():
  """Dump backtrace for all cached CVM worlds without executing ps command."""
  run_cmd(
      'vmdumper -g "===== CVM hang detected (Watchdog triggered). dumping'
      ' backtrace ====="'
  )

  target_wids = list(cached_wids)

  log_debug(f"Watchdog triggering vmdumper for WIDs: {target_wids}")
  for wid in target_wids:
    run_cmd(f"vmdumper {wid} backtrace")


def watchdog_thread():
  """Watchdog thread that checks LOGFILE modification time."""
  while True:
    time.sleep(2)
    if os.path.exists(LOGFILE):
      try:
        mtime = os.path.getmtime(LOGFILE)
        elapsed = time.time() - mtime

        if elapsed >= WATCHDOG_TIMEOUT:
          now_str = datetime.datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y")
          err_msg = (
              f"{now_str}: LOGFILE not updated for {int(elapsed)}s. Triggering"
              " vmdumper from watchdog.\n"
          )
          with open(LOGFILE, "a") as f:
            f.write(err_msg)

          dump_all_cvm_worlds()
      except Exception:
        pass


def main():
  parser = argparse.ArgumentParser(
      description="Monitor CVM status and dump backtrace."
  )
  parser.add_argument(
      "-d", "--debug", action="store_true", help="Enable debug mode output"
  )
  args = parser.parse_args()

  global DEBUG
  DEBUG = args.debug

  log_debug("Starting script...")

  # Start Watchdog Thread
  wd = threading.Thread(target=watchdog_thread, daemon=True)
  wd.start()

  # Collect GID and cache WIDs once before entering the main loop
  gid = get_cvm_gid()
  if gid:
    initialize_wids(gid)

  while True:
    # Guardrail for disk usage
    check_disk_usage()

    # Write current date to log file
    now_str = (
        datetime.datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y") + "\n"
    )
    with open(LOGFILE, "a") as f:
      f.write(now_str)

    # Process world status if GID is available
    if gid:
      # If ps -sjT hangs, watchdog thread will handle backtrace dumping using cached_wids
      ps_sjt_out = run_cmd("ps -sjT")
      gid_lines = [line for line in ps_sjt_out.splitlines() if gid in line]

      # Write world status to log file
      with open(LOGFILE, "a") as f:
        for line in gid_lines:
          f.write(line + "\n")
        f.write("\n")

    # Check and perform log rotation if needed
    rotate_logs()

    time.sleep(1)


if __name__ == "__main__":
  main()
