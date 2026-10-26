import os
import time
import streamlit as st
import streamlit.components.v1 as components
import folium
import requests
import pandas as pd
from streamlit_folium import st_folium
from math import radians, sin, cos, sqrt, atan2

st.set_page_config(page_title="SafePath", page_icon="🛡️", layout="wide")
gps_component = components.declare_component("safepath_gps", path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "gps_component"))

if "reports" not in st.session_state:
    st.session_state.reports = [
        {"location":"Demo report near MG Road","issue":"Broken Street Light","lat":12.9750,"lon":77.6000,"verified":False},
        {"location":"Demo report near metro exit","issue":"Dark or Isolated Stretch","lat":12.9680,"lon":77.5900,"verified":False}
    ]
for key, default in [("route_data",None),("gps_active",False),("last_gps",None),("last_reroute_time",0.0),("notice","")]:
    if key not in st.session_state: st.session_state[key]=default

def dist_m(a,b):
    radius=6371000
    p1,p2=radians(a[0]),radians(b[0]); dp=radians(b[0]-a[0]); dl=radians(b[1]-a[1])
    q=sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2
    return 2*radius*atan2(sqrt(q),sqrt(1-q))

def geocode(q):
    r=requests.get("https://nominatim.openstreetmap.org/search",params={"q":q,"format":"jsonv2","limit":1,"countrycodes":"in"},headers={"User-Agent":"SafePathHackathon/1.0"},timeout=20)
    r.raise_for_status(); data=r.json()
    return [float(data[0]["lat"]),float(data[0]["lon"])] if data else None

def get_routes(start,end):
    url=f"https://router.project-osrm.org/route/v1/driving/{start[1]},{start[0]};{end[1]},{end[0]}"
    # Ask OSRM for alternatives; it may still return only one route.
    r=requests.get(url,params={"overview":"full","geometries":"geojson","steps":"true","alternatives":3},timeout=30)
    r.raise_for_status(); j=r.json()
    return j.get("routes",[]) if j.get("code")=="Ok" else []

def route_distance(pos,route):
    coords=route.get("geometry",{}).get("coordinates",[])
    if not coords:return float("inf")
    return min(dist_m(pos,[p[1],p[0]]) for p in coords[::max(1,len(coords)//700)])

def route_risk_details(route):
    """Score only proximity to user-submitted reports; these are not verified safety data."""
    coords=route.get("geometry",{}).get("coordinates",[])
    if not coords:
        return {"score":0.0,"nearby":[]}
    sample=coords[::max(1,len(coords)//500)]
    nearby=[]
    score=0.0
    for rep in st.session_state.reports:
        nearest=min(dist_m([lat,lon],[rep["lat"],rep["lon"]]) for lon,lat in sample)
        if nearest < 200:
            contribution=max(0.0,(200-nearest)/200)
            score += contribution
            nearby.append({
                "issue":rep["issue"],
                "location":rep["location"],
                "distance_m":round(nearest),
                "contribution":round(contribution,2)
            })
    return {"score":round(score,2),"nearby":nearby}

def route_risk(route):
    return route_risk_details(route)["score"]

def choose_route(routes, preference):
    """Compare duration and report proximity for each route alternative."""
    assessed=[]
    for index, candidate in enumerate(routes):
        details=route_risk_details(candidate)
        duration_min=candidate.get("duration",0)/60
        # One full nearby-report score is weighted as 12 extra minutes.
        combined=duration_min + details["score"]*12
        assessed.append({
            "index":index+1,
            "route":candidate,
            "risk":details["score"],
            "nearby":details["nearby"],
            "duration_min":duration_min,
            "combined_score":combined
        })
    if preference=="Fastest Route":
        selected=min(assessed,key=lambda item:item["duration_min"])
    else:
        selected=min(assessed,key=lambda item:item["combined_score"])
    return selected, assessed

def next_turn(route,pos):
    coords=route.get("geometry",{}).get("coordinates",[])
    if not coords or not pos:return None
    idx=min(range(len(coords)),key=lambda i:dist_m(pos,[coords[i][1],coords[i][0]]))
    cum=[0.0]
    for i in range(1,len(coords)):cum.append(cum[-1]+dist_m([coords[i-1][1],coords[i-1][0]],[coords[i][1],coords[i][0]]))
    progress=cum[idx]; candidates=[]
    for leg in route.get("legs",[]):
        for step in leg.get("steps",[]):
            man=step.get("maneuver",{}); loc=man.get("location")
            if not loc or man.get("type") in ("depart","arrive"):continue
            mi=min(range(len(coords)),key=lambda i:dist_m([loc[1],loc[0]],[coords[i][1],coords[i][0]]))
            remaining=cum[mi]-progress
            if remaining>20:candidates.append((remaining,step,man))
    if candidates:
        remaining,step,man=min(candidates,key=lambda x:x[0])
        action=man.get("type","continue").replace("-"," ").title(); mod=man.get("modifier","")
        return {"distance":remaining,"action":f"{action} {mod}".strip(),"road":step.get("name") or "unnamed road"}
    end=[coords[-1][1],coords[-1][0]]; remaining=dist_m(pos,end)
    return {"distance":remaining,"action":"Arrive" if remaining<150 else "Continue straight","road":"destination" if remaining<150 else "follow the highlighted route"}

def fmt_time(seconds):
    mins=max(0,round(seconds/60)); h,m=divmod(mins,60)
    return f"{h} hr {m} min" if h else f"{m} min"

with st.sidebar:
    st.title("🛡️ SafePath")
    st.caption("Safety-aware navigation")
    st.header("📍 Plan Your Journey")
    with st.form("route_form"):
        start_text=st.text_input("Starting point",placeholder="e.g. Amity University, Bengaluru")
        end_text=st.text_input("Destination",placeholder="e.g. Doddaballapura, Karnataka")
        preference=st.radio("Route preference",["Fastest Route","Safety-Aware Route"])
        go=st.form_submit_button("🧭 See Directions",type="primary",use_container_width=True)
    if go:
        if not start_text.strip() or not end_text.strip():st.error("Enter both locations.")
        else:
            try:
                with st.spinner("Finding your route..."):
                    start=geocode(start_text.strip()); end=geocode(end_text.strip())
                    if not start:st.error("Starting point not found. Include city/state.")
                    elif not end:st.error("Destination not found. Include city/state.")
                    else:
                        routes=get_routes(start,end)
                        if not routes:st.error("No route found.")
                        else:
                            st.session_state.route_data={"start":start,"end":end,"start_text":start_text.strip(),"end_text":end_text.strip(),"preference":preference,"routes":routes}
                            st.session_state.gps_active=True;st.session_state.last_gps=None;st.session_state.notice=""
                            st.rerun()
            except requests.RequestException as e:st.error(f"Mapping service error: {e}")
    if st.button("■ Stop Navigation",use_container_width=True):
        st.session_state.gps_active=False;st.session_state.last_gps=None;st.rerun()
    st.divider()
    st.subheader("🚨 Emergency SOS")
    if st.button("TRIGGER SOS — DEMO",type="primary",use_container_width=True):
        st.warning("Simulation only. No SMS or emergency message was sent.")

# Keep the original dashboard sections available alongside navigation.
nav_tab, hazard_tab, analytics_tab, about_tab = st.tabs(["🗺️ Navigation","📢 Report Hazard","📊 Risk Analytics","ℹ️ About"])

with nav_tab:
    data=st.session_state.route_data
    if not data:
        st.info("Enter a start and destination in the sidebar, then click See Directions.")
        m=folium.Map(location=[12.9716,77.5946],zoom_start=12)
        for rep in st.session_state.reports:
            folium.Marker([rep["lat"],rep["lon"]],tooltip=f"{rep['issue']} — {rep['location']}",icon=folium.Icon(color="orange",icon="warning-sign")).add_to(m)
        st_folium(m,height=570,use_container_width=True,key="overview_map")
    else:
        gps=None
        if st.session_state.gps_active:
            val=gps_component(active=True,key="safepath_gps_live",default=None)
            if isinstance(val,dict) and val.get("lat") is not None and val.get("lon") is not None:
                gps={"lat":float(val["lat"]),"lon":float(val["lon"]),"accuracy":float(val.get("accuracy",999)),"heading":val.get("heading"),"speed":val.get("speed"),"timestamp":val.get("timestamp")}
                st.session_state.last_gps=gps
            else:gps=st.session_state.last_gps
        pos=[gps["lat"],gps["lon"]] if gps else None
        routes=data["routes"]
        selected, assessed_routes=choose_route(routes,data["preference"])
        route=selected["route"]
        turn=next_turn(route,pos) if pos else None
        st.subheader(f"{data['start_text']} → {data['end_text']}")
        st.caption("Foreground GPS only. Keep this page open and allow location access.")
        if len(routes) < 2:
            st.warning("The routing service returned only one route. SafePath cannot compare alternatives or avoid hazards on this trip; the displayed route is the only route returned.")
        elif data["preference"]=="Safety-Aware Route":
            if selected["nearby"]:
                labels=", ".join(sorted(set(item["issue"] for item in selected["nearby"])))
                st.info(f"Safety-aware selection: this route has a report-proximity score of {selected['risk']:.2f}. Nearby unverified reports: {labels}. The score is a heuristic, not a verified safety rating.")
            else:
                st.success("Safety-aware selection: no submitted reports were found within 200 m of this route. This does not prove the route is safe.")
        if gps:
            cols=st.columns(3)
            cols[0].metric("Next turn",f"{turn['distance']:.0f} m" if turn else "—")
            cols[1].metric("Travel time",fmt_time(route["duration"]))
            cols[2].metric("GPS accuracy",f"±{gps['accuracy']:.0f} m")
            if turn:st.info(f"➡️ **{turn['action']}** onto **{turn['road']}** in approximately **{turn['distance']:.0f} m**.")
            if gps["accuracy"]>100:st.warning("GPS accuracy is weak; the arrow may jump or appear off the road.")
            else:st.success("GPS active.")
        else:st.info("Navigation is ready. Click Request / refresh GPS permission below if the browser hasn't asked yet.")
        coords=route["geometry"]["coordinates"]
        center=pos if pos else data["start"]
        m=folium.Map(location=center,zoom_start=17 if pos else 13,control_scale=True)
        folium.PolyLine([[lat,lon] for lon,lat in coords],color="#2878ff",weight=7,opacity=.9,tooltip="Selected route").add_to(m)
        folium.Marker(data["start"],tooltip="Start",icon=folium.Icon(color="green",icon="play")).add_to(m)
        folium.Marker(data["end"],tooltip="Destination",icon=folium.Icon(color="red",icon="flag")).add_to(m)
        if pos:
            heading=gps.get("heading")
            arrow=f'<div style="font-size:34px;color:#1677ff;text-shadow:0 1px 3px white,1px 0 white,-1px 0 white;line-height:36px;transform:rotate({float(heading) if heading is not None else 0}deg)">▲</div>'
            folium.Marker(pos,tooltip=f"Your location · ±{gps['accuracy']:.0f} m",icon=folium.DivIcon(html=arrow,icon_size=(38,38),icon_anchor=(19,19))).add_to(m)
            folium.Circle(pos,radius=max(gps["accuracy"],10),color="#1677ff",fill=True,fill_opacity=.08,weight=1).add_to(m)
            m.location=pos
        else:m.fit_bounds([data["start"],data["end"]],padding=(25,25))
        for rep in st.session_state.reports:
            folium.Marker([rep["lat"],rep["lon"]],tooltip=f"{rep['issue']} — {rep['location']}",icon=folium.Icon(color="orange",icon="warning-sign")).add_to(m)
        st_folium(m,height=590,use_container_width=True,key="navigation_map")
        st.caption("Prototype limitation: map updates are not as fluid as Google Maps; no voice prompts or background tracking.")
        with st.expander("🛡️ Route comparison and hazard impact"):
            if len(assessed_routes) < 2:
                st.warning("No alternative route was returned by the routing service, so there is no comparison to show. Try different start/end points or retry later.")
            else:
                comparison = pd.DataFrame([{
                    "Route": f"Route {item['index']}",
                    "Travel time (min)": round(item["duration_min"],1),
                    "Nearby report score": item["risk"],
                    "Combined score (lower is preferred)": round(item["combined_score"],1),
                    "Nearby reports": len(item["nearby"])
                } for item in assessed_routes])
                st.dataframe(comparison, use_container_width=True, hide_index=True)
                st.caption("Safety-aware score = estimated travel minutes + 12 × report-proximity score. The weight is a prototype heuristic, not a validated safety model.")
                if data["preference"]=="Safety-Aware Route" and selected["nearby"]:
                    st.write("Reports influencing the selected route:")
                    for item in selected["nearby"]:
                        st.write(f"- **{item['issue']}** near {item['location']} (about {item['distance_m']} m from route; unverified)")
                elif data["preference"]=="Safety-Aware Route":
                    st.write("No submitted hazard report was within 200 m of the selected route.")
        with st.expander("🧭 Full turn-by-turn directions"):
            for leg in route.get("legs",[]):
                for i,step in enumerate(leg.get("steps",[]),1):
                    man=step.get("maneuver",{}); action=man.get("type","continue").replace("-"," ").title(); mod=man.get("modifier","")
                    st.write(f"{i}. {action} {mod} — {step.get('name') or 'unnamed road'} ({step.get('distance',0):.0f} m)")

with hazard_tab:
    st.header("📢 Report a Safety Hazard")
    st.write("Add a location-based report. Reports remain unverified.")
    with st.form("hazard_form"):
        place=st.text_input("Street or landmark")
        issue=st.selectbox("Issue type",["Broken Street Light","Dark or Isolated Stretch","Blocked Footpath","Suspicious Activity","Other Safety Concern"])
        lat=st.number_input("Latitude",min_value=-90.0,max_value=90.0,value=12.9716,format="%.6f")
        lon=st.number_input("Longitude",min_value=-180.0,max_value=180.0,value=77.5946,format="%.6f")
        submit=st.form_submit_button("Submit Hazard")
        if submit:
            if not place.strip():st.error("Enter a street or landmark.")
            else:
                st.session_state.reports.append({"location":place.strip(),"issue":issue,"lat":lat,"lon":lon,"verified":False})
                st.success("Hazard added to this session as an unverified report.")
with analytics_tab:
    st.header("📊 Area Risk Analytics")
    reports=st.session_state.reports
    a,b,c=st.columns(3);a.metric("Total reports",len(reports));b.metric("Verified",sum(r["verified"] for r in reports));c.metric("Unverified",sum(not r["verified"] for r in reports))
    st.bar_chart(pd.Series([r["issue"] for r in reports]).value_counts())
    for r in reversed(reports):st.write(f"📍 **{r['issue']}** — {r['location']} · {'Verified' if r['verified'] else 'Unverified'}")
with about_tab:
    st.header("ℹ️ About SafePath")
    st.markdown("""**Features:** Geocoding, road-route calculation, fastest/safety-aware route selection, foreground GPS marker, approximate next-turn guidance, hazard reporting, and basic risk analytics.

**Limitations:** GPS and turn distances are estimates. Public map services may be rate-limited. Hazard reports are unverified, the risk score is heuristic, no official lighting/crime/patrol data is connected, and SOS is only a simulation. This prototype does not guarantee safety.""")
