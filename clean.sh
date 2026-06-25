#!/usr/bin/env bash
# Remove built package artifacts.
find . -name "*.zst" -delete
find . -type d -name pkg -prune -exec rm -rf {} +
find . -type d -name src -prune -exec rm -rf {} +
