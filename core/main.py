import asyncio
import random
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import simpy
from core.twin_sim import VadodaraAirport

app = FastAPI(title="AeroTwin Backend", description="Vadodara Airport (VABO) Digital Twin Simulation API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "AeroTwin VABO Digital Twin API", "status": "running"}

@app.websocket("/ws/twin")
async def twin_stream(websocket: WebSocket):
    await websocket.accept()
    env = simpy.Environment()
    airport = VadodaraAirport(env)
    
    flight_counter = 100
    
    async def flight_generator():
        nonlocal flight_counter
        while True:
            risk = random.uniform(0.1, 0.9)
            env.process(airport.pushback_and_depart(f"IGO{flight_counter}", risk))
            flight_counter += 1
            await asyncio.sleep(8) # New flight every 8 seconds
            
    generator_task = asyncio.create_task(flight_generator())

    try:
        while True:
            # Advance simulation step if events exist
            if env.peek() != float('inf'):
                env.step()
            active_flights = [f for f in airport.flights.values() if f["status"] != "airborne"]
            await websocket.send_json({"flights": active_flights, "time": env.now})
            await asyncio.sleep(0.5)
    except Exception as e:
        print(f"Twin disconnected: {e}")
    finally:
        generator_task.cancel()
