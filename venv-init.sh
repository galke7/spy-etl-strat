#!/bin/bash

# Exit if error
set -e

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment"
    python3 -m venv venv
else
    echo "Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment"
source venv/bin/activate

# Install required packages
if [ -f "requirements.txt" ]; then
    echo "Installing required packages from requirements.txt"
    pip install --upgrade pip
    pip install -r requirements.txt
else
    echo "No requirements.txt file found"
fi

echo "Virtual environment setup complete"

# Deactivate virtual environment
#deactivate

# Exit script
#exit