import simpy
import math

class VadodaraAirport:
    def __init__(self, env):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}

    def pushback_and_depart(self, flight_id, risk_score):
        # 3D Coordinates: Center (0,0). Runway spans from X:-50, Z:-50 to X:50, Z:50.
        self.flights[flight_id] = {"id": flight_id, "x": 20, "y": 0, "z": -20, "heading": 0, "status": "pushback", "risk": risk_score}
        yield self.env.timeout(2)
        
        # Taxi to runway threshold (-50, -50)
        self.flights[flight_id]["status"] = "taxi"
        self.flights[flight_id]["heading"] = math.pi / 2
        for _ in range(5):
            self.flights[flight_id]["x"] -= (70 / 5)
            self.flights[flight_id]["z"] -= (30 / 5)
            yield self.env.timeout(1)

        # Queue for Runway
        with self.runway.request() as req:
            yield req
            self.flights[flight_id]["status"] = "takeoff_roll"
            self.flights[flight_id]["heading"] = -math.pi / 4 # 45 degrees
            
            # Takeoff roll to (50, 50)
            for i in range(10):
                self.flights[flight_id]["x"] += 10
                self.flights[flight_id]["z"] += 10
                if i > 5:
                    self.flights[flight_id]["y"] += 2 # Rotate pitch and climb
                yield self.env.timeout(1)
        
        self.flights[flight_id]["status"] = "airborne"
