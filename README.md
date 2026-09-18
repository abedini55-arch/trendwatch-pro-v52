# TrendWatch Pro V5.2

Mobile-first Persian dashboard for بورس، طلا و دلار.

- Google Trends: only observed values; no forecast data is fabricated.
- Real-person and legal/institutional money are separate.
- Smart Money remains unconnected until a verified source is available.
- FastAPI backend is included for deployment.

## Local
`uvicorn server:APP --host 0.0.0.0 --port 8000`

## Render
Build: `pip install -r requirements.txt`
Start: `uvicorn server:APP --host 0.0.0.0 --port $PORT`

Health: `/api/health`
Data: `/api/dashboard-data?range=12m&days=30`
