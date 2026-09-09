import asyncio
import random
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import simpy
from core.twin_sim import VadodaraAirport

app = FastAPI(title="AeroTwin VABO Digital Twin", description="Vadodara Airport 3D Digital Twin Engine")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "online", "airport": "VABO", "name": "Vadodara Airport 3D Twin"}

@app.websocket("/ws/twin")
async def twin_stream(websocket: WebSocket):
    await websocket.accept()
    env = simpy.Environment()
    airport = VadodaraAirport(env)
    
    flight_counter = 101
    
    async def flight_generator():
        nonlocal flight_counter
        # Initial aircraft at gate
        env.process(airport.pushback_and_depart(f"6E-{flight_counter}", random.uniform(0.15, 0.45)))
        flight_counter += 1
        
        while True:
            await asyncio.sleep(12)  # Launch flight every 12-14s
            risk = random.uniform(0.1, 0.9)
            airline_code = random.choice(["6E", "AI", "SG", "QP"])
            env.process(airport.pushback_and_depart(f"{airline_code}-{flight_counter}", risk))
            flight_counter += 1
            
    generator_task = asyncio.create_task(flight_generator())

    try:
        while True:
            # Advance simulation discrete step
            if env.peek() != float('inf'):
                env.step()
            active_flights = [f for f in airport.flights.values() if f["status"] != "airborne"]
            await websocket.send_json({
                "flights": active_flights,
                "time": round(env.now, 1),
                "airport": "VABO"
            })
            await asyncio.sleep(0.08)  # ~12 Hz streaming for smooth 3D interpolation
    except Exception as e:
        print(f"Twin WebSocket client disconnected: {e}")
    finally:
        generator_task.cancel()
