#!/usr/bin/env bash
# Which way turns the module off: update, recopy, or not at all?
set -uo pipefail; . "$(dirname "$0")/lib.sh"
W=$(mktemp -d); publish "$HERE/base-v2" "$W/base" v1.0.0; publish "$HERE/loop" "$W/loop" v1.0.0
mkproj(){ rm -rf "$W/p"; mkdir "$W/p"; cd "$W/p"; git init -q; cp_ copy -d project_name=demo "$W/base" .; commit_all . base
  cp_ copy --answers-file .copier-answers.loop.yml "$W/loop" .; commit_all . loop-on; }
mkproj; step "on: files the module added"; git show --stat --format= HEAD
step "A. update with loop_enabled=false"; cp_ update -a .copier-answers.loop.yml -d loop_enabled=false; git status --short
mkproj; step "B. recopy with loop_enabled=false"; cp_ recopy -a .copier-answers.loop.yml -d loop_enabled=false --overwrite; git status --short
mkproj; step "C. update, no new template version, no change"; cp_ update -a .copier-answers.loop.yml; git status --short
