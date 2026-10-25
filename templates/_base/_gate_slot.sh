#!/usr/bin/env bash
# Run a heavy gate part (a test suite) holding one of this host's gate slots, which every worktree
# and project on the host shares, so agents working in parallel queue their gates instead of
# overloading the host together. `check:unit` calls it.
#
#   gate-slot COMMAND [ARG...]
#
# GATE_SLOTS (default 1) is how many gates run at once. A slot is a lock on a file, so it frees
# itself when the command exits, however it exits. GATE_JOBS, exported to the command, is the cores
# free when it starts (online cores minus the 1-minute load average, at least 1): a parallel runner
# reads it, e.g. `pytest -n "$GATE_JOBS"`, instead of adding a worker per core on a loaded host.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage: gate-slot COMMAND [ARG...]" >&2; exit 2; }
slots="${GATE_SLOTS:-1}"
[[ "$slots" =~ ^[1-9][0-9]*$ ]] || { echo "gate-slot: GATE_SLOTS=$slots is no positive count" >&2; exit 2; }
dir="${XDG_CACHE_HOME:-$HOME/.cache}/engineering-loop"
mkdir -p "$dir"
cores="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)"
load="$(LC_ALL=C uptime | sed -E 's/.*load averages?: *([0-9.]+).*/\1/')"
GATE_JOBS="$(awk -v c="$cores" -v l="$load" 'BEGIN { f = int(c - l); print (f < 1 ? 1 : (f > c ? c : f)) }')"
export GATE_JOBS

# perl, since macOS ships no flock(1); the lock's descriptor stays open across exec, so the command holds it.
exec perl -MFcntl=:flock -e '
  my ($dir, $slots, @command) = @ARGV;
  $^F = 1023;
  my ($said, $held);
  until ($held) {
    for my $i (1 .. $slots) {
      open(my $fh, ">>", "$dir/gate.$i.lock") or die "gate-slot: $dir/gate.$i.lock: $!\n";
      if (flock($fh, LOCK_EX | LOCK_NB)) {
        truncate($fh, 0); syswrite($fh, "$$\n"); $held = $fh; last;
      }
    }
    next if $held;
    unless ($said++) {
      my $pid = do { local @ARGV = ("$dir/gate.1.lock"); my $line = <> // ""; chomp $line; $line };
      print STDERR "gate-slot: waiting for a host gate slot (held by pid ", ($pid || "unknown"), ")\n";
    }
    sleep 2;
  }
  exec { $command[0] } @command or die "gate-slot: $command[0]: $!\n";
' "$dir" "$slots" "$@"
