# SafePath — Safety Routing Upgrade

## Run
```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Route selection
- Requests up to three OSRM route alternatives (the public service may return only one).
- Fastest Route selects the shortest estimated duration.
- Safety-Aware Route scores each returned route using proximity to user-submitted hazard reports and travel time.
- Shows a route comparison table and reports which unverified hazards influence the selected route.
- If only one route is returned, the app clearly says it cannot compare alternatives or avoid reported hazards on that trip.

## Limitations
The hazard score is a prototype heuristic based on report proximity, not a validated safety prediction. Reports are unverified and stored only in the current Streamlit session. Public routing/geocoding services can be rate-limited. GPS is foreground-only and SOS is a simulation.
