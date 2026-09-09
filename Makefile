.PHONY: dev web test fmt up

dev:            ## run the gateway with reload on :8080
	cd server && uvicorn app.main:app --reload --port 8080

web:            ## run the playground on :5173
	cd web && npm run dev

test:
	cd server && python -m pytest -q

up:
	docker compose up --build
