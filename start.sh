#!/bin/bash
APP=${1:?"Usage: $0 <app-name>"}
PROJECT="$(cd "$(dirname "$0")" && pwd)"

exec claude \
  --add-dir "$PROJECT/skills/$APP" \
  --add-dir "$PROJECT/common" \
  "${@:2}"
