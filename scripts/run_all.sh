#!/usr/bin/env bash
set -e
# Launch order matters: agents up first so the orchestrator can discover their
# A2A cards at startup. Frontend serves at http://localhost:3000.
( cd agents/news      && uvicorn main:app --port 8101 ) &
( cd agents/reviews_a && uvicorn main:app --port 8102 ) &
( cd agents/reviews_b && uvicorn main:app --port 8103 ) &
sleep 2   # let agents publish their cards
( cd orchestrator     && uvicorn main:app --port 8000 ) &
( cd frontend         && npm run dev ) &
wait
