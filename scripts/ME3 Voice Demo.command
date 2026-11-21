#!/bin/bash
set -eu
cd "$(dirname "$0")/.."
exec ./scripts/me3.sh agent --me3-voice-mode demo
