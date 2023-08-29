#!/bin/bash

if [ $# -lt 1 ]; then
  echo "Usage: $0 <repository_url> [ssh_key_flag]"
  exit 1
fi

repository_url=$1
ssh_key_flag=$2

# Check if ssh_key_flag is present
echo "Checking if SSH key should be used"

if [ "$ssh_key_flag" ]; then
  # Check if SSH key exists
  ssh_key_path="/root/.ssh/keycloak-theme-ssh.pem"

  if [ ! -f "$ssh_key_path" ]; then
    echo "  SSH key not found at $ssh_key_path"
    # Don't raise an error here to not break init container run
  else
    echo "  SSH key found at $ssh_key_path"
    # validate key permissions and check if it's not empty
    if [ ! -s "$ssh_key_path" ]; then
      echo "  SSH key is empty"
      # Don't raise an error here to not break init container run
    else

        if [ "$(stat -c %a "$ssh_key_path")" != "600" ]; then
          echo "SSH key permissions are too open, setting to 600"

          chwon 1000:1000 "$ssh_key_path" 2>/dev/null
          chmod 600 "$ssh_key_path" 2>/dev/null

          if [ $? -eq 0 ]; then
            echo "  SSH key permissions set to 600"
          else
            echo "  Failed to set SSH key permissions to 600"
            # show key permissions and system info
            echo "  SSH key permissions: $(stat -c %a "$ssh_key_path")"
            echo "  User info: $(id)"
            # Don't raise an error here to not break init container run
          fi

        fi

        # Start SSH agent and add key
        echo "Starting SSH agent and adding key"
        eval $(ssh-agent -s)
        ssh-add "$ssh_key_path"
        echo "/n"

        # configure git to avoid checking host keys
        git config --global core.sshCommand "ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no"
        # congigure git to use ssh key
        git config --global core.sshCommand "ssh -i $ssh_key_path"
    fi
  fi
fi

cd /opt/data/custom-themes # Change to data directory, should be mounted as volume

# Attempt Git operations with error handling
if [ ! -d themes/.git ]; then
  echo "Git repository not found, cloning repository"

  git clone "$repository_url" themes --verbose 2>/dev/null

  if [ $? -eq 0 ]; then
    echo "  Git clone operation succeeded"
  else
    echo "  Git clone operation failed : $repository_url"
    # Don't raise an error here to not break init container run
  fi
else
  echo "Git repository already cloned, pulling changes"

  git -C themes pull --verbose 2>/dev/null

  if [ $? -eq 0 ]; then
    echo "  Git pull operation succeeded"
  else
    echo "  Git pull operation failed : $repository_url"
    # Don't raise an error here to not break init container run
  fi
fi
