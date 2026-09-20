#!/bin/sh

# Run this script with setsid on ESX, which detaches the process from ssh session.
# Ex: setsid /scratch/collect_debug.sh > /dev/null 2>&1 &
#
# This script collects CVM VM status every second. If more than 4 worlds are stuck at SEMA status,
# dump world status with vmdumper <wid> backtrace command.

LOGFILE="/scratch/pss.out"
MAX_SIZE=335544320
MAX_FILES=3
USAGE_LIMIT=80

while true
do

  # Guardrail to prevent /scratch full. Exit if the usage reaches USAGE_LIMIT.
  
  USAGE=$(df /scratch | awk 'END{print $5}' | sed 's/%//')
  if [ -n "$USAGE" ] && [ "$USAGE" -ge "$USAGE_LIMIT" ]; then
    echo "$(date): /scratch usage reached ${USAGE}%. Exiting script to prevent disk full." >> "$LOGFILE"
    exit 1
  fi

  date >> "$LOGFILE"

  # collect gid of CVM VM, then write worlds status to the log file.
  gid=$(ps -j | grep "vcpu-0:INSTALLING" | awk '{print $2}')
  ps -sjT | grep $gid >> "$LOGFILE"
  echo >> "$LOGFILE"

  # Check the number of SEMA state worlds.
  nsema=$(ps -sjT | grep $gid | grep SEMA | grep -v svga | wc -l)

  # Dump the backtrace of each world to vmkernel.log if more than 4 worlds are stuck at SEMA state
  if [ $nsema -ge 4 ];then
     vmdumper -g "===== CVM is getting hung. dumping backtrace ====="
     for i in $(ps -sjT | grep $gid | awk '{print $1}')
     do
       vmdumper $i backtrace
     done
  fi
  
  # Rotate LOGIFLE if the file size is more than MAX_SIZE.
  # Keep MAX_FILES log files
  
  if [ -f "$LOGFILE" ]; then
    SIZE=$(stat -c%s "$LOGFILE")
    if [ "$SIZE" -ge "$MAX_SIZE" ]; then
      n=$((MAX_FILES - 1))
      while [ $n -ge 1 ]
      do
        next=$((n + 1))
        [ -f "${LOGFILE}.${n}" ] && mv -f "${LOGFILE}.${n}" "${LOGFILE}.${next}"
        n=$((n - 1))
      done

      # Rename the latest log file to $LOGFILE.1 and create a new log file
      mv -f "$LOGFILE" "${LOGFILE}.1"
      touch "$LOGFILE"
    fi
  fi

  sleep 1
done
