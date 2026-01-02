#!/bin/bash
# Setup passwordless sudo for the current user in WSL
# Run this script from WSL: bash tools/setup-wsl-sudo.sh

echo "Setting up passwordless sudo..."
echo "You may be prompted for your password once."

# Add the current user to sudoers with NOPASSWD
sudo bash -c "echo '$(whoami) ALL=(ALL) NOPASSWD: ALL' | tee /etc/sudoers.d/$(whoami)-nopasswd"
sudo chmod 0440 /etc/sudoers.d/$(whoami)-nopasswd

echo "Passwordless sudo configured! You can now run sudo commands without a password."
