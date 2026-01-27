#!/bin/bash

echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting InnoFrance App..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload