PYTHON ?= python3
PIP ?= pip3
FRONTEND_DIR := frontend
BACKEND_DIR := backend

.PHONY: install-backend install-frontend dev-backend dev-frontend format lint docker-build

install-backend:
	$(PIP) install -r $(BACKEND_DIR)/requirements.txt

install-frontend:
	cd $(FRONTEND_DIR) && npm install

dev-backend:
	cd $(BACKEND_DIR) && uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

dev-frontend:
	cd $(FRONTEND_DIR) && npm run dev

format:
	$(PYTHON) -m black $(BACKEND_DIR)/app

docker-build:
	docker build -t xfolder:latest .
