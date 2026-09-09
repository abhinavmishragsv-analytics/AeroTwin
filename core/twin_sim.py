import simpy
import math

class VadodaraAirport:
    def __init__(self, env):
        self.env = env
        self.runway = simpy.Resource(env, capacity=1)
        self.flights = {}

    def pushback_and_depart(self, flight_id, risk_score):
        # VABO Apron Coordinates
        lat, lng = 22.3330, 73.2200
        self.flights[flight_id] = {"id": flight_id, "lat": lat, "lng": lng, "heading": 45, "status": "pushback", "risk": risk_score}
        yield self.env.timeout(2)
        
        # Taxiing to Runway 04 threshold
        self.flights[flight_id]["status"] = "taxi"
        for _ in range(4):
            lat += 0.0005
            lng += 0.0008
            self.flights[flight_id].update({"lat": lat, "lng": lng})
            yield self.env.timeout(1)

        # Takeoff Roll along Runway 04
        with self.runway.request() as req:
            yield req
            self.flights[flight_id]["status"] = "takeoff_roll"
            for _ in range(6):
                lat += 0.0010
                lng += 0.0012
                self.flights[flight_id].update({"lat": lat, "lng": lng})
                yield self.env.timeout(1)
        
        self.flights[flight_id]["status"] = "airborne"
